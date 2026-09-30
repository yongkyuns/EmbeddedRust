/* SPDX-License-Identifier: MIT
 * Test-only post-close fault injection. The real NuttX close runs first and
 * its released number is immediately reused by a sentinel. Returning -6 then
 * models the consumed-descriptor/error combination in fdlist_close/file_put,
 * without deliberately leaking an inode through a failing lower-half close.
 * The production bridge source is unchanged; only its test-build close symbol
 * is renamed to rc_nx_close_real by this fixture's Makefile.
 */
#include <nuttx/config.h>
#include <nuttx/fs/fs.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <unistd.h>
#include "bridge.h"

#define PROBE_PATH "/dev/nxrs-close-probe"

int rc_nx_close_real(int fd);

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static bool g_active;
static pthread_t g_owner;
static unsigned int g_attempts;
static int g_consumed = -1;
static int g_sentinel = -1;
static int g_real_result = -1;

static ssize_t probe_read(struct file *filep, char *buffer, size_t length)
{
  (void)filep;
  (void)buffer;
  (void)length;
  return 0;
}

static int probe_ioctl(struct file *filep, int command, unsigned long argument)
{
  struct rc_device_format *format = (void *)(uintptr_t)argument;
  (void)filep;
  if (command != RCIOC_FORMAT) return -ENOTTY;
  if (format == NULL) return -EINVAL;
  *format = (struct rc_device_format){2, 2, 0};
  return 0;
}

static const struct file_operations g_probe_ops =
{
  .read = probe_read,
  .ioctl = probe_ioctl,
};

int rc_test_close_prepare(void)
{
  return register_driver(PROBE_PATH, &g_probe_ops, 0600, NULL);
}

int rc_test_close_arm(void)
{
  pthread_mutex_lock(&g_lock);
  if (g_active)
    {
      pthread_mutex_unlock(&g_lock);
      return -1;
    }
  g_owner = pthread_self();
  g_attempts = 0;
  g_consumed = -1;
  g_sentinel = -1;
  g_real_result = -1;
  g_active = true;
  pthread_mutex_unlock(&g_lock);
  return 0;
}

int rc_nx_close(int fd)
{
  bool inject = false;
  int result;
  pthread_mutex_lock(&g_lock);
  if (g_active && pthread_equal(g_owner, pthread_self()))
    inject = ++g_attempts == 1;
  pthread_mutex_unlock(&g_lock);

  result = rc_nx_close_real(fd);
  if (!inject) return result;

  pthread_mutex_lock(&g_lock);
  g_real_result = result;
  g_consumed = fd;
  if (result == 0) g_sentinel = open("/dev/null", O_RDWR);
  pthread_mutex_unlock(&g_lock);
  return -6; /* Synthetic I/O error AFTER the actual target close. */
}

int rc_test_close_check(void)
{
  int result;
  pthread_mutex_lock(&g_lock);
  result = g_active && pthread_equal(g_owner, pthread_self()) &&
           g_attempts == 1 && g_real_result == 0 && g_sentinel >= 0 &&
           g_sentinel == g_consumed && fcntl(g_sentinel, F_GETFD) >= 0 ? 0 : -1;
  pthread_mutex_unlock(&g_lock);
  return result;
}

int rc_test_close_finish(void)
{
  int fd;
  int result = rc_test_close_check();
  pthread_mutex_lock(&g_lock);
  fd = g_sentinel;
  g_sentinel = -1;
  g_active = false;
  pthread_mutex_unlock(&g_lock);
  if (fd < 0 || close(fd) < 0) result = -1;
  /* Negative control: the sentinel check must detect a real extra close. */
  errno = 0;
  if (fcntl(fd, F_GETFD) != -1 || errno != EBADF) result = -1;
  if (unregister_driver(PROBE_PATH) < 0) result = -1;
  if (result == 0)
    printf("RC_TARGET_CLOSE attempts=1 reused=1 survivor=1 control=closed OK\n");
  return result;
}
