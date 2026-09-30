/* SPDX-License-Identifier: MIT */
#ifndef NXRS_BENCH_POSIX_H
#define NXRS_BENCH_POSIX_H
#include <stdint.h>

struct rb_heap_snapshot
{
  int supported;
  int arena;
  int used;
  int free_bytes;
  int peak;
  int largest_free;
  int allocated_chunks;
};
/* The opaque object keeps platform-specific sem_t/mqd_t layouts out of Rust. */
void *rb_open(unsigned kind, unsigned capacity);
int rb_step(void *object, uint32_t sequence);
int rb_close(void *object);
uint64_t rb_now_ns(void);
uint64_t rb_resolution_ns(void);
int rb_policy(void);
int rb_priority(void);
int rb_heap_snapshot(struct rb_heap_snapshot *out);
/* Same shim and operation loop used by the independent C executable. */
int rb_c_run(unsigned kind, unsigned count, unsigned capacity);
#endif
