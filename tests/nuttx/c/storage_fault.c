/* SPDX-License-Identifier: MIT
 * Test-only syscall interposition for the unchanged production bridge.
 * All successful I/O below reaches the real NuttX VFS/tmpfs. Faults affect
 * only the selected descriptor on the owning thread. No host filesystem,
 * fake append implementation, or production fault-injection state is used.
 */
#include <nuttx/config.h>
#include <sys/types.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "bridge.h"

#define PATH "/rcam/storage-fault.rcam"
#define RECORD_BYTES 44

enum fault
{
  SHORT_EINTR = 1, HEADER_FULL, PAYLOAD_IO, ZERO_WRITE,
  SEEK_ERROR, ROLLBACK_TRUNCATE, ROLLBACK_SEEK, FLUSH_RETRY
};
enum counter { WRITES, INTERRUPTS, ERRORS, BYTES, TRUNCATES, SEEKS, SYNCS, COUNTERS };
static const char *const names[] =
{
  "", "short_eintr", "header_full", "payload_io", "zero_write",
  "seek_end", "rollback_truncate", "rollback_seek", "flush_retry"
};
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static struct
{
  bool active;
  bool armed;
  bool fired;
  pthread_t owner;
  int fd;
  unsigned int mode;
  unsigned int phase;
  uint32_t calls[COUNTERS];
  uint32_t snapshot[COUNTERS];
} state;

int rc_nx_file_create_real(const char *path);

static bool selected(int fd)
{
  /* Every caller holds lock, including calls from unrelated target threads. */
  return state.active && state.armed && state.fd == fd &&
         pthread_equal(state.owner, pthread_self());
}

int rc_test_storage_begin(unsigned int mode)
{
  int result = -1;
  pthread_mutex_lock(&lock);
  if (!state.active && mode >= SHORT_EINTR && mode <= FLUSH_RETRY)
    {
      memset(&state, 0, sizeof(state));
      state.owner = pthread_self();
      state.mode = mode;
      state.fd = -1;
      state.active = true;
      result = 0;
    }
  pthread_mutex_unlock(&lock);
  return result;
}

int rc_nx_file_create(const char *path)
{
  int fd = rc_nx_file_create_real(path);
  pthread_mutex_lock(&lock);
  if (fd >= 0 && state.active && state.fd < 0 &&
      pthread_equal(state.owner, pthread_self()) && strcmp(path, PATH) == 0)
    state.fd = fd;
  pthread_mutex_unlock(&lock);
  return fd;
}

int rc_test_storage_arm(void)
{
  int result = -1;
  pthread_mutex_lock(&lock);
  if (state.active && !state.armed && state.fd >= 0 &&
      pthread_equal(state.owner, pthread_self()) &&
      lseek(state.fd, 0, SEEK_END) == RECORD_BYTES)
    {
      state.armed = true;
      result = 0;
    }
  pthread_mutex_unlock(&lock);
  return result;
}

ssize_t rc_test_storage_write(int fd, const void *bytes, size_t length)
{
  ssize_t result;
  int saved;
  pthread_mutex_lock(&lock);
  if (!selected(fd))
    {
      pthread_mutex_unlock(&lock);
      return write(fd, bytes, length);
    }
  state.calls[WRITES]++;
  if (state.mode == SHORT_EINTR && !state.fired)
    {
      state.fired = true;
      state.calls[INTERRUPTS]++;
      result = -1;
      errno = EINTR;
    }
  else if (state.mode >= HEADER_FULL && state.mode <= ROLLBACK_SEEK &&
           state.mode != SEEK_ERROR && !state.fired)
    {
      /* Fail inside the header or after two actual payload bytes. */
      size_t limit = state.mode == HEADER_FULL || state.mode == ZERO_WRITE ? 5 : 42;
      size_t remaining = limit - state.calls[BYTES];
      if (remaining == 0)
        {
          state.fired = true;
          state.calls[ERRORS]++;
          result = state.mode == ZERO_WRITE ? 0 : -1;
          errno = state.mode == HEADER_FULL ? ENOSPC : EIO;
        }
      else
        result = write(fd, bytes, length < remaining ? length : remaining);
    }
  else
    result = write(fd, bytes, state.mode == SHORT_EINTR && length > 7 ? 7 : length);
  if (result > 0) state.calls[BYTES] += (uint32_t)result;
  saved = errno;
  pthread_mutex_unlock(&lock);
  errno = saved;
  return result;
}

int rc_test_storage_truncate(int fd, off_t length)
{
  int result;
  int saved;
  pthread_mutex_lock(&lock);
  if (!selected(fd))
    {
      pthread_mutex_unlock(&lock);
      return ftruncate(fd, length);
    }
  state.calls[TRUNCATES]++;
  if (state.mode == ROLLBACK_TRUNCATE)
    {
      state.calls[ERRORS]++;
      result = -1;
      errno = EIO;
    }
  else result = ftruncate(fd, length);
  saved = errno;
  pthread_mutex_unlock(&lock);
  errno = saved;
  return result;
}

off_t rc_test_storage_seek(int fd, off_t offset, int whence)
{
  off_t result;
  int saved;
  pthread_mutex_lock(&lock);
  if (!selected(fd))
    {
      pthread_mutex_unlock(&lock);
      return lseek(fd, offset, whence);
    }
  state.calls[SEEKS]++;
  if ((state.mode == SEEK_ERROR && !state.fired && whence == SEEK_END) ||
      (state.mode == ROLLBACK_SEEK && whence == SEEK_SET))
    {
      state.fired = true;
      state.calls[ERRORS]++;
      result = -1;
      errno = EIO;
    }
  else result = lseek(fd, offset, whence);
  saved = errno;
  pthread_mutex_unlock(&lock);
  errno = saved;
  return result;
}

int rc_test_storage_sync(int fd)
{
  int result;
  int saved;
  pthread_mutex_lock(&lock);
  if (!selected(fd))
    {
      pthread_mutex_unlock(&lock);
      return fsync(fd);
    }
  state.calls[SYNCS]++;
  if (state.mode == FLUSH_RETRY && !state.fired)
    {
      state.fired = true;
      state.calls[ERRORS]++;
      result = -1;
      errno = EIO;
    }
  else result = fsync(fd);
  saved = errno;
  pthread_mutex_unlock(&lock);
  errno = saved;
  return result;
}

static bool poisoned(void)
{
  return state.mode == ROLLBACK_TRUNCATE || state.mode == ROLLBACK_SEEK;
}

static size_t expected_length(unsigned int phase)
{
  if (state.mode == ROLLBACK_TRUNCATE) return RECORD_BYTES + 42;
  if (state.mode == ROLLBACK_SEEK) return RECORD_BYTES;
  return phase == 2 || state.mode == SHORT_EINTR || state.mode == FLUSH_RETRY ?
         2 * RECORD_BYTES : RECORD_BYTES;
}

static void put_le64(uint8_t *out, uint64_t value)
{
  for (unsigned int i = 0; i < 8; i++) out[i] = (uint8_t)(value >> (8 * i));
}

/* Independent C verifier: reopen the file and compare every actual byte,
 * including a deliberately incomplete suffix after failed truncation.
 */
static int image(size_t length, bool emit)
{
  uint8_t expected[2 * RECORD_BYTES] = {0};
  uint8_t actual[2 * RECORD_BYTES + 1];
  size_t used = 0;
  int fd = open(PATH, O_RDONLY);
  int result = -1;
  if (fd < 0) return -1;
  for (unsigned int i = 0; i < 2; i++)
    {
      uint8_t *record = expected + i * RECORD_BYTES;
      memcpy(record, "RCAMREC1", 8);
      record[8] = 2;
      record[10] = 2;
      put_le64(record + 16, i + 1);
      put_le64(record + 24, UINT64_C(0x1122334455660000) + i + 1);
      put_le64(record + 32, 4);
      for (unsigned int j = 0; j < 4; j++) record[40 + j] = i + 1 + j;
    }
  while (used < sizeof(actual))
    {
      ssize_t n = read(fd, actual + used, sizeof(actual) - used);
      if (n < 0 && errno == EINTR) continue;
      if (n < 0) goto done;
      if (n == 0) break;
      used += (size_t)n;
    }
  if (used != length || memcmp(actual, expected, length) != 0) goto done;
  if (emit)
    {
      printf("RC_STORAGE case=%s phase=%s data=", names[state.mode],
             state.phase == 1 ? "before" : "after");
      for (size_t i = 0; i < used; i++) printf("%02x", actual[i]);
      printf(" calls=");
      for (unsigned int i = 0; i < COUNTERS; i++)
        printf("%s%lu", i == 0 ? "" : ",", (unsigned long)state.calls[i]);
      printf("\n");
    }
  result = 0;
done:
  if (close(fd) < 0) result = -1;
  return result;
}

int rc_test_storage_check(unsigned int phase)
{
  int result = -1;
  size_t length;
  off_t position;
  pthread_mutex_lock(&lock);
  if (!selected(state.fd) || phase != state.phase + 1 || phase > 2) goto done;
  length = expected_length(phase);
  position = state.mode == ROLLBACK_SEEK ? RECORD_BYTES + 42 : (off_t)length;
  if (lseek(state.fd, 0, SEEK_CUR) != position) goto done;
  if (phase == 2 && poisoned() &&
      memcmp(state.snapshot, state.calls, sizeof(state.calls)) != 0) goto done;
  state.phase = phase;
  result = image(length, true);
  if (phase == 1) memcpy(state.snapshot, state.calls, sizeof(state.calls));
done:
  pthread_mutex_unlock(&lock);
  return result;
}

int rc_test_storage_finish(void)
{
  uint8_t corrupt = 0, original = 'R';
  int result = -1;
  int fd = -1;
  size_t length;
  pthread_mutex_lock(&lock);
  if (!state.active || state.phase != 2 ||
      !pthread_equal(state.owner, pthread_self())) goto done;
  errno = 0;
  if (fcntl(state.fd, F_GETFD) != -1 || errno != EBADF) goto done;
  length = expected_length(2);
  /* Negative control changes real storage, not a success marker. The C
   * verifier must reject the corruption, then accept the restored bytes. */
  fd = open(PATH, O_RDWR);
  if (fd < 0 || write(fd, &corrupt, 1) != 1 || image(length, false) == 0 ||
      lseek(fd, 0, SEEK_SET) != 0 || write(fd, &original, 1) != 1 ||
      image(length, false) != 0) goto done;
  if (close(fd) < 0) { fd = -1; goto done; }
  fd = -1;
  if (unlink(PATH) < 0) goto done;
  state.active = false;
  printf("RC_STORAGE_DONE case=%s closed=1 control=rejected OK\n", names[state.mode]);
  result = 0;
done:
  if (fd >= 0) close(fd);
  pthread_mutex_unlock(&lock);
  return result;
}
