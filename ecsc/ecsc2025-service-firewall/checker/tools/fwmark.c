#include <err.h>
#include <errno.h>
#include <net/if.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char *argv[])
{
    char *end;
    if (argc != 3)
        errx(EXIT_FAILURE, "usage: fwmark <fd> <fwmark>");

    end = NULL;
    long fd = strtol(argv[1], &end, 0);
    if (!end || *end != '\0')
        errx(EXIT_FAILURE, "fd (%s) must be a number", argv[1]);

    end = NULL;
    unsigned long mark = strtoul(argv[2], &end, 0);
    if (!end || *end != '\0')
        errx(EXIT_FAILURE, "fwmark (%s) must be a number", argv[2]);

    if (mark > UINT32_MAX)
        errx(EXIT_FAILURE, "fwmark (%lx) is too large", mark);

    unsigned fwmark = mark;
    if (setsockopt(fd, SOL_SOCKET, SO_MARK, &fwmark, sizeof(fwmark)))
        err(errno, "failed to set SO_MARK socket option");

    return EXIT_SUCCESS;
}
