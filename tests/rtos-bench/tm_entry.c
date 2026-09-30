/* SPDX-License-Identifier: MIT */
#include <stdio.h>
#ifndef TM_TEST_DURATION
#define TM_TEST_DURATION 30
#endif
extern void tm_main(void);
int main(int argc, char **argv)
{
  (void)argc; (void)argv;
  puts("TM_PORT reconstruction: FIFO priority=220-tm_priority; stack=8192; queue=8x16; malloc=128; single-core");
  printf("TM_PORT window_seconds=%d; one test per boot; preserve ERROR lines\n", TM_TEST_DURATION);
  tm_main();
  return 1;
}
