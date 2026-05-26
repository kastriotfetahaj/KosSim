#include <err.h>
#include <errno.h>
#include <linux/if_tun.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char *argv[])
{
    char *end;
    if (argc != 4)
        errx(EXIT_FAILURE, "usage: tunctl <fd> <flags> <name>");

    end = NULL;
    long fd = strtol(argv[1], &end, 0);
    if (!end || *end != '\0')
        errx(EXIT_FAILURE, "fd (%s) must be a number", argv[1]);

    end = NULL;
    unsigned long flags = strtoul(argv[2], &end, 0);
    if (!end || *end != '\0')
        errx(EXIT_FAILURE, "flags (%s) must be a number", argv[2]);

    const char *name = argv[3];
    if (strlen(name) <= 0 || strlen(name) >= IFNAMSIZ)
        errx(EXIT_FAILURE, "interface name (%s) is too long", name);

    struct ifreq req;
    memset(&req, 0, sizeof(req));
    strncpy(req.ifr_name, name, IFNAMSIZ);
    req.ifr_flags = flags;

    if (ioctl(fd, TUNSETIFF, &req))
        err(errno, "failed to invoke TUNSETIFF ioctl");

    return EXIT_SUCCESS;
}
