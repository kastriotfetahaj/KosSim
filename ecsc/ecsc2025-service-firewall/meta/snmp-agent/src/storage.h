#include "storage_custom.h"
#include "storage_monitoring.h"

struct Storage {
    int n_custom;
    uint64_t monitoring[N_MONITORING_VALUES];
    CustomEntry_t custom[MAX_CUSTOM_ENTRIES];
    // enough padding that any read to monitoring with a 32 bit index will never go into unmapped memory
    uint64_t padding[UINT_MAX];
};

extern struct Storage *storage;

int init_storage(void);
