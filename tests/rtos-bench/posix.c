/* SPDX-License-Identifier: MIT
 * Public POSIX calls only. No Rust or Nxrs dependency. Setup is not timed.
 * A/B comparisons share these non-inlined shim calls, NOT a raw-syscall cost.
 */
#ifdef __NuttX__
#include <nuttx/config.h>
#include <malloc.h>
#endif
#define _POSIX_C_SOURCE 200809L
#include "posix.h"
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <mqueue.h>
#include <pthread.h>
#include <sched.h>
#include <semaphore.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

struct object
{
  unsigned kind;
  sem_t sem;
  mqd_t queue;
  sem_t request;
  sem_t response;
  sem_t ready;
  pthread_t worker;
  volatile int stop;
};
static const char *const names[] = {
  "semaphore-hot", "heap128", "queue-hot", "yield-alone", "semaphore-handoff"
};

static int wait_sem(sem_t *sem)
{
  int rc;
  do { rc = sem_wait(sem); } while (rc != 0 && errno == EINTR);
  return rc;
}

static void *handoff_worker(void *arg)
{
  struct object *o = arg;
  if (sem_post(&o->ready) != 0) return (void *)1;
  for (;;) {
    if (wait_sem(&o->request) != 0) return (void *)1;
    if (o->stop) break;
    if (sem_post(&o->response) != 0) return (void *)1;
  }
  return NULL;
}

static uint64_t ns(struct timespec t)
{
  return (uint64_t)t.tv_sec * UINT64_C(1000000000) + (uint64_t)t.tv_nsec;
}
__attribute__((noinline)) uint64_t rb_now_ns(void)
{
  struct timespec t;
  if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) abort();
  return ns(t);
}
uint64_t rb_resolution_ns(void)
{
  struct timespec t;
  if (clock_getres(CLOCK_MONOTONIC, &t) != 0) abort();
  return ns(t);
}
int rb_policy(void)
{
  int policy; struct sched_param p;
  return pthread_getschedparam(pthread_self(), &policy, &p) == 0 ? policy : -1;
}
int rb_priority(void)
{
  int policy; struct sched_param p;
  return pthread_getschedparam(pthread_self(), &policy, &p) == 0 ? p.sched_priority : -1;
}
int rb_heap_snapshot(struct rb_heap_snapshot *out)
{
  if (!out) return -1;
  memset(out, 0, sizeof(*out));
#ifdef __NuttX__
  struct mallinfo info = mallinfo();
  out->supported = 1;
  out->arena = info.arena;
  out->used = info.uordblks;
  out->free_bytes = info.fordblks;
  out->peak = info.usmblks;
  out->largest_free = info.mxordblk;
  out->allocated_chunks = info.aordblks;
#else
  out->supported = 0;
#endif
  return 0;
}
void *rb_open(unsigned kind, unsigned capacity)
{
  if (kind > 4 || capacity == 0 || capacity > 8) { errno = EINVAL; return NULL; }
  struct object *o = calloc(1, sizeof(*o));
  if (!o) return NULL;
  o->kind = kind;
  if (kind == 0 && sem_init(&o->sem, 0, 1) != 0) { free(o); return NULL; }
  if (kind == 2) {
    struct mq_attr attr = {0};
    attr.mq_maxmsg = (long)capacity; attr.mq_msgsize = 16;
    o->queue = (mqd_t)-1;
    /* O_EXCL: never open/unlink someone else's queue. Immediately unlink ours. */
    for (unsigned i = 0; i < 32; ++i) {
      char name[64];
      snprintf(name, sizeof(name), "/nxrs-bench-%ld-%u", (long)getpid(), i);
      o->queue = mq_open(name, O_CREAT | O_EXCL | O_RDWR | O_NONBLOCK, 0600, &attr);
      if (o->queue != (mqd_t)-1) {
        if (mq_unlink(name) != 0) { mq_close(o->queue); free(o); return NULL; }
        break;
      }
      if (errno != EEXIST) break;
    }
    if (o->queue == (mqd_t)-1) { free(o); return NULL; }
  }
  if (kind == 4) {
    int request_ok = 0, response_ok = 0, ready_ok = 0, attr_ok = 0;
    pthread_attr_t attr;
    if (sem_init(&o->request, 0, 0) != 0) goto handoff_fail;
    request_ok = 1;
    if (sem_init(&o->response, 0, 0) != 0) goto handoff_fail;
    response_ok = 1;
    if (sem_init(&o->ready, 0, 0) != 0) goto handoff_fail;
    ready_ok = 1;
    if (pthread_attr_init(&attr) != 0) goto handoff_fail;
    attr_ok = 1;
    if (pthread_attr_setstacksize(&attr, 32768) != 0) goto handoff_fail;
    if (pthread_create(&o->worker, &attr, handoff_worker, o) != 0) goto handoff_fail;
    pthread_attr_destroy(&attr);
    if (wait_sem(&o->ready) != 0) {
      o->stop = 1;
      sem_post(&o->request);
      pthread_join(o->worker, NULL);
      goto handoff_fail_noattr;
    }
    return o;
handoff_fail:
    if (attr_ok) pthread_attr_destroy(&attr);
handoff_fail_noattr:
    if (ready_ok) sem_destroy(&o->ready);
    if (response_ok) sem_destroy(&o->response);
    if (request_ok) sem_destroy(&o->request);
    free(o);
    return NULL;
  }
  return o;
}
__attribute__((noinline)) int rb_step(void *object, uint32_t sequence)
{
  struct object *o = object;
  switch (o->kind) {
    case 0:
      if (sem_trywait(&o->sem) != 0) return -1;
      return sem_post(&o->sem);
    case 1: {
      volatile unsigned char *p = malloc(128);
      if (!p) return -1;
      /* Observable accesses prevent allocate/free elimination, in both A/B. */
      p[0] = (unsigned char)sequence; p[127] = (unsigned char)~sequence;
      int ok = p[0] == (unsigned char)sequence && p[127] == (unsigned char)~sequence;
      free((void *)p);
      return ok ? 0 : -1;
    }
    case 2: {
      uint32_t tx[4] = {sequence, ~sequence, 0x12345678u, 0x87654321u}, rx[4];
      if (mq_send(o->queue, (const char *)tx, sizeof(tx), 0) != 0) return -1;
      ssize_t length = mq_receive(o->queue, (char *)rx, sizeof(rx), NULL);
      return length == (ssize_t)sizeof(rx) && memcmp(tx, rx, sizeof(tx)) == 0 ? 0 : -1;
    }
    case 3: return sched_yield(); /* No assertion that another thread runs. */
    case 4:
      if (sem_post(&o->request) != 0) return -1;
      return wait_sem(&o->response);
    default: return -1;
  }
}
int rb_close(void *object)
{
  struct object *o = object;
  int result = 0;
  if (o->kind == 0) result = sem_destroy(&o->sem);
  if (o->kind == 2) result = mq_close(o->queue);
  if (o->kind == 4) {
    void *status = NULL;
    o->stop = 1;
    if (sem_post(&o->request) != 0) result = -1;
    if (pthread_join(o->worker, &status) != 0 || status != NULL) result = -1;
    if (sem_destroy(&o->ready) != 0) result = -1;
    if (sem_destroy(&o->response) != 0) result = -1;
    if (sem_destroy(&o->request) != 0) result = -1;
  }
  free(o);
  return result;
}
int rb_c_run(unsigned kind, unsigned count, unsigned capacity)
{
  if (kind > 4 || count == 0 || count > 10000000) return 1;
  struct rb_heap_snapshot heap_before, heap_setup, heap_active, heap_after;
  rb_heap_snapshot(&heap_before);
  void *o = rb_open(kind, capacity);
  if (!o) { perror("rb_open"); return 1; }
  rb_heap_snapshot(&heap_setup);
  int result = 0;
  for (unsigned i = 0; i < 100; ++i) if (rb_step(o, i)) { result = 1; break; }
  uint64_t start = rb_now_ns();
  unsigned completed = 0;
  if (!result) for (; completed < count; ++completed) if (rb_step(o, completed)) { result = 1; break; }
  uint64_t elapsed = rb_now_ns() - start;
  rb_heap_snapshot(&heap_active);
  if (rb_close(o)) result = 1;
  rb_heap_snapshot(&heap_after);
  if (result || elapsed == 0) { fprintf(stderr, "RTBENCH FAIL c-posix\n"); return 1; }
  printf("RTBENCH {\"schema\":1,\"backend\":\"c-posix\",\"case\":\"%s\","
         "\"iterations\":%u,\"capacity\":%u,\"elapsed_ns\":%" PRIu64 ","
         "\"clock_resolution_ns\":%" PRIu64 ",\"policy\":%d,\"priority\":%d,"
         "\"instrumentation\":\"interval-only\",\"valid\":true,"
         "\"heap_supported\":%s,\"heap_used_before\":%d,\"heap_used_setup\":%d,"
         "\"heap_used_active\":%d,\"heap_used_after\":%d,"
         "\"heap_peak_before\":%d,\"heap_peak_after\":%d,"
         "\"heap_largest_free_before\":%d,\"heap_largest_free_after\":%d}\n",
         names[kind], completed, capacity, elapsed, rb_resolution_ns(), rb_policy(), rb_priority(),
         heap_before.supported ? "true" : "false", heap_before.used, heap_setup.used,
         heap_active.used, heap_after.used, heap_before.peak, heap_after.peak,
         heap_before.largest_free, heap_after.largest_free);
  return 0;
}
