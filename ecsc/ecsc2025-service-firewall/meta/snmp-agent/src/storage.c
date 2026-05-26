#define _LARGEFILE64_SOURCE
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>

#include "storage.h"

struct Storage *storage;

int init_storage(void) {
    char *storage_path = getenv("SNMP_STORAGE_FILE");
    if (storage_path == NULL) {
        storage_path = "custom_storage";
    }
    int storage_file = -1;
    int flags = MAP_SHARED;
#ifdef FUZZING
    flags |= MAP_ANONYMOUS;
#else
    storage_file = open(storage_path, O_CREAT | O_RDWR | O_LARGEFILE, S_IRUSR | S_IWUSR | S_IRGRP | S_IWGRP);
    if (storage_file == -1) {
        fprintf(stderr, "storage: open()\n");
        return -1;
    }
    if (ftruncate64(storage_file, sizeof(struct Storage)) == -1) {
        fprintf(stderr, "storage: ftruncate()\n");
        return -1;
    }
#endif
    size_t map_size = (sizeof(struct Storage) + sysconf(_SC_PAGE_SIZE) - 1) & ~(sysconf(_SC_PAGE_SIZE) - 1);
    storage = mmap(NULL, map_size, PROT_READ | PROT_WRITE, flags, storage_file, 0);
    if (storage == MAP_FAILED) {
        fprintf(stderr, "storage: mmap()\n");
        return -1;
    }
#ifndef FUZZING
    if (close(storage_file) == -1) {
        fprintf(stderr, "storage: close()\n");
        return -1;
    }
#endif
    return 0;
}
