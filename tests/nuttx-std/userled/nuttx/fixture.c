/* Target-only qualification. The native ioctl/VFS and USERLED upper half are
 * real NuttX. This instrumented lower half does NOT claim physical GPIO output.
 */
#include <nuttx/config.h>
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <fcntl.h>
#include <nuttx/fs/fs.h>
#include <nuttx/leds/userled.h>

#define TEST_PATH "/dev/nxrs-userled"
#define SUPPORTED UINT32_C(0x80000005)

static uint32_t g_state;
static uint32_t g_calls;
static unsigned g_bad_opens;
static unsigned g_bad_ioctls;
static unsigned g_bad_closes;
static bool g_invalid_lower_call;

static userled_set_t supported(FAR const struct userled_lowerhalf_s *lower)
{
  (void)lower;
  return SUPPORTED;
}

static void setled(FAR const struct userled_lowerhalf_s *lower, int led, bool on)
{
  (void)lower;
  ++g_calls;
  if (led < 0 || led >= 32 || (SUPPORTED & (UINT32_C(1) << led)) == 0)
    {
      g_invalid_lower_call = true;
      return;
    }
  uint32_t bit = UINT32_C(1) << led;
  if (on) g_state |= bit;
  else g_state &= ~bit;
}

static void setall(FAR const struct userled_lowerhalf_s *lower, userled_set_t set)
{
  (void)lower;
  g_state = set;
}

static const struct userled_lowerhalf_s g_lower =
{
  .ll_supported = supported,
  .ll_setled = setled,
  .ll_setall = setall,
};

static int bad_open(FAR struct file *filep)
{
  (void)filep;
  ++g_bad_opens;
  return 0;
}

static int bad_close(FAR struct file *filep)
{
  (void)filep;
  ++g_bad_closes;
  return 0;
}

static int bad_ioctl(FAR struct file *filep, int cmd, unsigned long arg)
{
  (void)filep;
  (void)arg;
  ++g_bad_ioctls;
  return cmd == ULEDIOC_SUPPORTED ? -EIO : -ENOTTY;
}

static const struct file_operations g_bad_ops =
{
  .open = bad_open,
  .close = bad_close,
  .ioctl = bad_ioctl,
};

int nxrs_userled_fixture_install(int phase)
{
  if (phase == 0) return register_driver(TEST_PATH, &g_bad_ops, 0666, NULL);
  if (phase != 1 || g_bad_opens != 1 || g_bad_ioctls != 1 || g_bad_closes != 1)
    return -EIO;
  int ret = unregister_driver(TEST_PATH);
  if (ret < 0) return ret;
  return userled_register(TEST_PATH, &g_lower);
}

int nxrs_userled_fixture_verify(uint32_t state, uint32_t calls)
{
  return !g_invalid_lower_call && g_state == state && g_calls == calls ? 0 : -EIO;
}

int nxrs_userled_fixture_fds(void)
{
  /* Controlled single-owner fixture: only stdio and one transient device fd.
   * Check a bounded range before/while/after every open, so even the first leak
   * fails. This is descriptor recovery, not a general kernel heap/leak census.
   */
  int count = 0;
  for (int fd = 0; fd < 64; ++fd)
    {
      if (fcntl(fd, F_GETFD) >= 0) ++count;
      else if (errno != EBADF) return -errno;
    }
  return count;
}
