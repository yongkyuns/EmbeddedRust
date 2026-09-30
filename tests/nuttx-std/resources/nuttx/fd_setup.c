/* Test-only preconditions around rustc's generated C-ABI main. Not app hosting. */
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

extern int rust_resources_probe_main(int argc, char **argv);

static unsigned int count_bits(unsigned int mask)
{
  return (mask & 1) + ((mask >> 1) & 1) + ((mask >> 2) & 1);
}

int main(int argc, char **argv)
{
  if (argc == 2 && strcmp(argv[1], "resources") == 0)
    {
      return rust_resources_probe_main(argc, argv);
    }

  bool reject = argc == 2 && strcmp(argv[1], "fds-reject") == 0;
  if (!reject && (argc != 3 || strcmp(argv[1], "fds") != 0 ||
                 strlen(argv[2]) != 1 || argv[2][0] < '0' || argv[2][0] > '7'))
    {
      return 2;
    }

  unsigned int mask = reject ? 7 : (unsigned int)(argv[2][0] - '0');
  for (int fd = 0; fd < 3; ++fd)
    {
      if (fcntl(fd, F_GETFD) < 0)
        {
          return 3;
        }
    }
  int report = dup(1);
  if (report < 3)
    {
      return 4;
    }
  unsigned int closed = 0;
  bool valid = true;
  for (int fd = 0; fd < 3; ++fd)
    {
      if ((mask & (1u << fd)) != 0)
        {
          /* Negative control intentionally omits one required close. */
          if (!(reject && fd == 2) && close(fd) < 0)
            {
              valid = false;
            }
          errno = 0;
          if (fcntl(fd, F_GETFD) == -1 && errno == EBADF)
            {
              ++closed;
            }
        }
    }
  valid = valid && closed == count_bits(mask);
  int result = 1;
  if (!valid)
    {
      dprintf(report, "NXRS_FD_SETUP_REJECTED\n");
    }
  else
    {
      dprintf(report, "NXRS_FD_PREPARED {\"mask\":%u,\"closed\":%u}\n", mask, closed);
      /* This preserves std initialization and cleanup, once per fresh kernel. */
      result = rust_resources_probe_main(argc, argv);
      unsigned int recovered = 0;
      for (int fd = 0; fd < 3; ++fd)
        {
          if ((mask & (1u << fd)) != 0 && fcntl(fd, F_GETFD) >= 0)
            {
              ++recovered;
            }
        }
      dprintf(report, "NXRS_FD_RETURN {\"mask\":%u,\"recovered\":%u,\"rust_status\":%d}\n",
              mask, recovered, result);
      if (recovered != closed)
        {
          result = 1;
        }
    }
  /* Restore the test task's console before normal NuttX teardown. */
  for (int fd = 0; fd < 3; ++fd)
    {
      if ((mask & (1u << fd)) != 0 && dup2(report, fd) < 0)
        {
          result = 1;
        }
    }
  close(report);
  return result;
}
