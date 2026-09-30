/* SPDX-License-Identifier: MIT */
#include "posix.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv)
{
  const char *names[] = {"semaphore-hot", "heap128", "queue-hot", "yield-alone", "semaphore-handoff"};
  if (argc != 3) { fprintf(stderr, "usage: rt_c CASE ITERATIONS\n"); return 2; }
  unsigned kind;
  for (kind = 0; kind < 5; ++kind) if (!strcmp(names[kind], argv[1])) break;
  errno = 0; char *end;
  unsigned long count = strtoul(argv[2], &end, 10);
  if (kind == 5 || errno || !*argv[2] || *end || count == 0 || count > 10000000 || argv[2][0] == '-') return 2;
  return rb_c_run(kind, (unsigned)count, 8);
}
