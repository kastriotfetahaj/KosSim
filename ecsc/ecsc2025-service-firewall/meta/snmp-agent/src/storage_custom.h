#include "general.h"
#include <time.h>

#define KEY_LEN (8*2)
#define MAX_CUSTOM_ENTRIES 100000
#define CUSTOM_ENTRY_LIVETIME (60 * 30) // live for 30 minutes
#define CUSTOM_CLEANUP_INTERVAL (60 * 1) // once per minute
#define CUSTOM_MAX_LEN 88

typedef struct CustomEntry {
    uint8_t key[KEY_LEN];
    time_t create_time;
    size_t length;
    uint8_t text[CUSTOM_MAX_LEN];
} CustomEntry_t;

int custom_init(void);
void clean_custom_entries(void);
void custom_reset(void);
int custom_is_var(netsnmp_variable_list *var);
int custom_get_next(netsnmp_variable_list *var, oid *out_name, size_t *out_length);
void custom_get(netsnmp_variable_list *var, int *errstat);
void custom_set(netsnmp_variable_list *var, int *errstat);
