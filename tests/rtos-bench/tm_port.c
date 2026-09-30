/* SPDX-License-Identifier: MIT
 * Nxrs's own Thread-Metric NuttX adapter; not the report author's adapter.
 * Generic upstream loops and their counter validation are left byte-identical.
 */
#include <nuttx/config.h>
#include "tm_api.h"
#include <errno.h>
#include <fcntl.h>
#include <mqueue.h>
#include <pthread.h>
#include <sched.h>
#include <semaphore.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#ifdef CONFIG_SMP
#error "Unmodified Thread-Metric counter/snapshot assumptions require this single-core fixture"
#endif
_Static_assert(sizeof(unsigned long) == 4, "Thread-Metric messages must be 16 bytes, not LP64's 32 bytes");
static struct worker { pthread_t thread; sem_t start, resume; void (*entry)(void); int priority; } workers[6];
static sem_t signals[1];
static mqd_t queue;
static unsigned created;
static void require(int ok)
{
  if (!ok) { fprintf(stderr, "TM_PORT FAIL errno=%d\n", errno); abort(); }
}
static void wait_token(sem_t *s)
{
  int rc;
  do { rc = sem_wait(s); } while (rc && errno == EINTR);
  require(rc == 0);
}
static void *entry(void *arg)
{
  struct worker *w = arg;
  wait_token(&w->start);
  wait_token(&w->resume);
  int policy; struct sched_param p;
  require(pthread_getschedparam(pthread_self(), &policy, &p) == 0);
  require(policy == SCHED_FIFO && p.sched_priority == w->priority);
  w->entry();
  return NULL;
}
void tm_initialize(void (*initialize)(void))
{
  initialize();
  /* No worker enters the unmodified test before ALL test resources exist.
   * Releasing under sched_lock also lets the high-priority reporter start first.
   * NuttX declares sched_lock/sched_unlock void; neither has a status to test.
   */
  sched_lock();
  for (unsigned i = 0; i < 6; ++i) if (created & (1u << i)) require(sem_post(&workers[i].start) == 0);
  sched_unlock();
  for (;;) pause(); /* One test per boot, external capture/reset after two windows. */
}
int tm_thread_create(int id, int priority, void (*fn)(void))
{
  require(id >= 0 && id < 6 && !(created & (1u << id)));
  struct worker *w = &workers[id];
  w->entry = fn; w->priority = 220 - priority;
  require(sem_init(&w->start, 0, 0) == 0 && sem_init(&w->resume, 0, 0) == 0);
  pthread_attr_t a; struct sched_param p = {0}; p.sched_priority = w->priority;
  require(pthread_attr_init(&a) == 0);
  require(pthread_attr_setstacksize(&a, 8192) == 0);
  require(pthread_attr_setinheritsched(&a, PTHREAD_EXPLICIT_SCHED) == 0);
  require(pthread_attr_setschedpolicy(&a, SCHED_FIFO) == 0);
  require(pthread_attr_setschedparam(&a, &p) == 0);
  require(pthread_create(&w->thread, &a, entry, w) == 0);
  require(pthread_attr_destroy(&a) == 0);
  created |= 1u << id;
  return TM_SUCCESS;
}
int tm_thread_resume(int id) { return sem_post(&workers[id].resume) == 0 ? TM_SUCCESS : TM_ERROR; }
int tm_thread_suspend(int id) { wait_token(&workers[id].resume); return TM_SUCCESS; }
void tm_thread_relinquish(void) { sched_yield(); }
void tm_thread_sleep(int seconds)
{
  struct timespec remaining = {seconds, 0};
  int rc;
  do { rc = nanosleep(&remaining, &remaining); } while (rc && errno == EINTR);
  require(rc == 0);
}
int tm_queue_create(int id)
{
  require(id == 0);
  struct mq_attr a = {0}; a.mq_maxmsg = 8; a.mq_msgsize = 16;
  char name[48]; snprintf(name, sizeof(name), "/tm-%ld", (long)getpid());
  queue = mq_open(name, O_CREAT | O_EXCL | O_RDWR | O_NONBLOCK, 0600, &a);
  require(queue != (mqd_t)-1);
  require(mq_unlink(name) == 0);
  return TM_SUCCESS;
}
int tm_queue_send(int id, unsigned long *p) { (void)id; return mq_send(queue, (char *)p, 16, 0) == 0 ? TM_SUCCESS : TM_ERROR; }
int tm_queue_receive(int id, unsigned long *p) { (void)id; return mq_receive(queue, (char *)p, 16, NULL) == 16 ? TM_SUCCESS : TM_ERROR; }
int tm_semaphore_create(int id) { require(sem_init(&signals[id], 0, 1) == 0); return TM_SUCCESS; }
int tm_semaphore_get(int id) { return sem_trywait(&signals[id]) == 0 ? TM_SUCCESS : TM_ERROR; }
int tm_semaphore_put(int id) { return sem_post(&signals[id]) == 0 ? TM_SUCCESS : TM_ERROR; }
int tm_memory_pool_create(int id) { (void)id; return TM_SUCCESS; }
int tm_memory_pool_allocate(int id, unsigned char **p) { (void)id; *p = malloc(128); return *p ? TM_SUCCESS : TM_ERROR; }
int tm_memory_pool_deallocate(int id, unsigned char *p) { (void)id; free(p); return TM_SUCCESS; }
