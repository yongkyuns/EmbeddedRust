/* SPDX-License-Identifier: MIT
 * Target-only qualification. No production application or HAL policy here.
 */
#include <nuttx/config.h>
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <sched.h>
#include <semaphore.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "bridge.h"

#define ABI_TAG UINT64_C(0x1122334455667788)
#define ABI_LENGTH 17

extern uint64_t rc_rust_abi_probe(uint8_t *, size_t, uint64_t,
                                uint64_t (*)(uint8_t *, size_t, uint64_t));

static uint64_t abi_callback(uint8_t *bytes, size_t length, uint64_t tag)
{
  if (length != ABI_LENGTH || tag != ABI_TAG) return 0;
  for (size_t i = 0; i < length; i++)
    if (bytes[i] != (uint8_t)(i ^ 0x5a)) return 0;
  bytes[length - 1] ^= 0x80;
  return tag ^ ((uint64_t)length << 40);
}

static int check_abi(void)
{
  uint8_t guarded[ABI_LENGTH + 2];
  uint64_t callback_result = ABI_TAG ^ ((uint64_t)ABI_LENGTH << 40);
  uint64_t expected = ((callback_result << 7) | (callback_result >> 57)) ^ ABI_TAG;
  memset(guarded, 0xa5, sizeof(guarded));
  uint64_t result = rc_rust_abi_probe(guarded + 1, ABI_LENGTH, ABI_TAG, abi_callback);
  if (result != expected || guarded[0] != 0xa5 || guarded[ABI_LENGTH + 1] != 0xa5)
    return -1;
  for (size_t i = 0; i < ABI_LENGTH; i++)
    if (guarded[i + 1] != (uint8_t)((i ^ 0x5a) ^ (i == ABI_LENGTH - 1 ? 0x80 : 0)))
      return -1;
  printf("RC_TARGET_ABI bits=%u OK\n", (unsigned int)(sizeof(void *) * CHAR_BIT));
  return 0;
}

#ifdef CONFIG_EXAMPLES_RUSTCAM_PREEMPTION
_Static_assert(ATOMIC_INT_LOCK_FREE == 2, "test loop needs lock-free integer atomics");

struct preemption
{
  sem_t ready;
  sem_t go;
  atomic_uint active;
  atomic_uint stop;
  atomic_uint work;
  unsigned int wakes;
  int error;
  int lock_scheduler;
};

static int wait_sem(sem_t *semaphore)
{
  while (sem_wait(semaphore) < 0)
    if (errno != EINTR) return -1;
  return 0;
}

static void *high_priority(void *argument)
{
  struct preemption *test = argument;
  unsigned int previous = 0;
  sem_post(&test->ready);
  if (wait_sem(&test->go) != 0) { test->error = 2; goto done; }
  if (!atomic_load_explicit(&test->active, memory_order_acquire))
    { test->error = 1; goto done; }
  for (unsigned int i = 0; i < 4; i++)
    {
      while (usleep(20000) < 0)
        if (errno != EINTR) { test->error = 2; break; }
      if (test->error != 0) break;
      unsigned int work = atomic_load_explicit(&test->work, memory_order_relaxed);
      if (!atomic_load_explicit(&test->active, memory_order_acquire) || work <= previous)
        { test->error = 1; break; }
      previous = work;
      test->wakes++;
    }
done:
  atomic_store_explicit(&test->stop, 1, memory_order_release);
  return NULL;
}

static void *cpu_bound(void *argument)
{
  struct preemption *test = argument;
  const unsigned int limit = test->lock_scheduler ? 10000 : 500000000;
  if (test->lock_scheduler) sched_lock();
  atomic_store_explicit(&test->active, 1, memory_order_release);
  sem_post(&test->go);
  /* No sleeps, yields, clock calls, or syscalls in the workload. Only a target
   * timer interrupt can wake and schedule the higher-priority sleeper while
   * this single-core FIFO task is running. The finite cap is a fail-safe,
   * not a cycle/timing assertion. Host harness timeout is the outer bound.
   */
  for (unsigned int i = 1; i <= limit; i++)
    {
      if (atomic_load_explicit(&test->stop, memory_order_acquire)) break;
      atomic_store_explicit(&test->work, i, memory_order_relaxed);
    }
  atomic_store_explicit(&test->active, 0, memory_order_release);
  if (test->lock_scheduler) sched_unlock();
  return NULL;
}

static int start_thread(pthread_t *thread, int priority,
                        void *(*entry)(void *), void *argument)
{
  pthread_attr_t attributes;
  struct sched_param scheduling;
  int result = pthread_attr_init(&attributes);
  if (result != 0) return result;
  memset(&scheduling, 0, sizeof(scheduling));
  scheduling.sched_priority = priority;
  result = pthread_attr_setinheritsched(&attributes, PTHREAD_EXPLICIT_SCHED);
  if (result == 0) result = pthread_attr_setschedpolicy(&attributes, SCHED_FIFO);
  if (result == 0) result = pthread_attr_setschedparam(&attributes, &scheduling);
  if (result == 0) result = pthread_attr_setstacksize(&attributes, 4096);
  if (result == 0) result = pthread_create(thread, &attributes, entry, argument);
  pthread_attr_destroy(&attributes);
  return result;
}

static int preemption_trial(int lock_scheduler, unsigned int *work)
{
  struct preemption test;
  pthread_t high;
  pthread_t low;
  int result = -1;
  memset(&test, 0, sizeof(test));
  atomic_init(&test.active, 0);
  atomic_init(&test.stop, 0);
  atomic_init(&test.work, 0);
  test.lock_scheduler = lock_scheduler;
  if (sem_init(&test.ready, 0, 0) < 0) return -1;
  if (sem_init(&test.go, 0, 0) < 0) { sem_destroy(&test.ready); return -1; }
  if (start_thread(&high, 160, high_priority, &test) != 0) goto cleanup;
  if (wait_sem(&test.ready) != 0 || start_thread(&low, 80, cpu_bound, &test) != 0)
    {
      sem_post(&test.go);
      if (pthread_join(high, NULL) != 0) abort();
      goto cleanup;
    }
  if (pthread_join(low, NULL) != 0 || pthread_join(high, NULL) != 0) abort();
  *work = atomic_load_explicit(&test.work, memory_order_relaxed);
  if (lock_scheduler)
    result = (test.error == 1 && test.wakes == 0 && *work == 10000) ? 0 : -1;
  else
    result = (test.error == 0 && test.wakes == 4 && *work > 0) ? 0 : -1;
cleanup:
  sem_destroy(&test.go);
  sem_destroy(&test.ready);
  return result;
}
#endif

int rc_target_qualify(void)
{
  if (check_abi() != 0) return -1;
#ifdef CONFIG_EXAMPLES_RUSTCAM_PREEMPTION
  unsigned int work = 0;
  unsigned int control_work = 0;
  if (preemption_trial(0, &work) != 0 || preemption_trial(1, &control_work) != 0)
    return -1;
  printf("RC_TARGET_PREEMPT wakes=4 control_wakes=0 work=%u OK\n", work);
#endif
  return 0;
}
