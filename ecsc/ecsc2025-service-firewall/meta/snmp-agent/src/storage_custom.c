#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/mman.h>
#include <time.h>

#include "snmp_helpers.h"
#include "storage.h"

oid custom_name[MAX_OID_LEN];
size_t custom_name_len = MAX_OID_LEN;

int custom_init(void) {
    if (snmp_parse_oid("CustomValue", custom_name, &custom_name_len) == NULL) {
        printf("Couldn't parse oid %s\n", "Custom");
        return -1;
    }
    if (storage->n_custom > MAX_CUSTOM_ENTRIES || storage->n_custom < 0) {
        fprintf(stderr, "Custom storage corrupted(1), resetting storage\n");
        custom_reset();
    }
    time_t current = time(NULL);
    for (int i = 0; i < storage->n_custom; i++) {
        CustomEntry_t *entry = storage->custom + i;
        if (entry->length > CUSTOM_MAX_LEN || entry->create_time > current) {
            fprintf(stderr, "Custom storage corrupted(2), resetting storage\n");
            custom_reset();
            break;
        }
    }
    return 0;
}

int custom_entry_create(CustomEntry_t *entry, uint8_t *text, size_t length) {
    entry->create_time = time(NULL);
    memcpy(entry->text, text, length);
    entry->length = length;
    return 0;
}

void custom_entry_delete(CustomEntry_t *entry) {
    bzero(entry, sizeof(*entry));
}

int custom_find_entry(uint8_t *key, size_t key_len, int *next) {
    int first = 0, middle, last = storage->n_custom - 1, cmp;
	while (first <= last) {
        middle = (first+last)/2;
        cmp = memcmp(&storage->custom[middle].key, key, key_len);
		if (cmp < 0) {
			first = middle + 1;
		} else if (cmp > 0) {
			last = middle - 1;
		} else {
            if (next != NULL) {
                if (middle != storage->n_custom - 1) {
                    *next = middle + 1;
                } else {
                    *next = -1;
                }
            }
			return middle;
		}
	}

    if (next != NULL) {
        if (first != storage->n_custom) {
            *next = first;
        } else {
            *next = -1;
        }
    }

	return -1;
}

int custom_add_entry(uint8_t *key) {
    if (storage->n_custom >= MAX_CUSTOM_ENTRIES) {
        printf("Warning: custom storage is full\n");
        return -1;
    }
    int next;
    int entry = custom_find_entry(key, KEY_LEN, &next);
    if (entry != -1) {
        // entry already exists
        return -1;
    }

    if (next != -1) {
        assert(next < storage->n_custom);
        // make room for the entry
        memmove(&storage->custom[next + 1], &storage->custom[next], sizeof(CustomEntry_t) * (storage->n_custom - next));
    } else {
        next = storage->n_custom;
    }
    storage->n_custom++;
    memcpy(storage->custom[next].key, key, KEY_LEN);
    // function changes the storage, do a sync
    // async is fine as the process continues to run
    if (msync(storage, sizeof(struct Storage), MS_ASYNC) == -1) {
        fprintf(stderr, "msync failed\n");
    }
    return next;
}

void clean_custom_entries(void) {
    int prev = -1, n_del = 0;
    time_t cutoff = time(NULL) - CUSTOM_ENTRY_LIVETIME;
    for (int curr = 0; curr < storage->n_custom; curr++) {
        if (storage->custom[curr].create_time < cutoff) {
            if (prev != -1) {
                assert(prev - n_del >= 0);
                // move all entries from the previous deleted on up to before this one backwards
                // this will move one further for every entry that has been removed
                memmove(&storage->custom[prev - n_del], &storage->custom[prev + 1], sizeof(CustomEntry_t) * (curr - prev - 1));
                n_del++;
            }
            prev = curr;
        }
    }

    if (prev != -1) {
        // move the remaining entries backwards to fille the space from deleted entries
        memmove(&storage->custom[prev - n_del], &storage->custom[prev + 1], sizeof(CustomEntry_t) * (storage->n_custom - prev - 1));
        n_del++;

        // clear the remaining space
        bzero(&storage->custom[storage->n_custom - n_del], sizeof(CustomEntry_t) * n_del);
        storage->n_custom -= n_del;
    }

    // function changes the storage, do a sync
    // async is fine as the process continues to run
    if (msync(storage, sizeof(struct Storage), MS_ASYNC) == -1) {
        fprintf(stderr, "msync failed\n");
    }
    DBG_PRINTF("Cleaned up %d custom entries\n", n_del);
}

void custom_reset(void) {
    storage->n_custom = 0;
    bzero(storage->custom, sizeof(*storage->custom));
}

void custom_key_to_oid(uint8_t *key, oid *name, size_t *name_length) {
    for (int i = 0; i < KEY_LEN; i++) {
        name[i] = key[i];
    }
    *name_length = KEY_LEN;
}

void custom_oid_to_key(uint8_t *key, oid *name, size_t name_length) {
    size_t i = 0;
    for (; i < KEY_LEN && i < name_length; i++) {
        key[i] = name[i];
    }
    for (; i < KEY_LEN; i++) {
        key[i] = 0;
    }
}

int custom_is_var(netsnmp_variable_list *var) {
    if (var->name_length != custom_name_len + KEY_LEN) {
        DBG_PRINTF("custom_is_var name length mismatch: %zu vs %zu\n", var->name_length, custom_name_len + KEY_LEN);
        return 0;
    }
    if (snmp_oid_compare(var->name, var->name_length - KEY_LEN, custom_name, custom_name_len) != 0) {
        DBG_PRINTF("custom_is_var name mismatch\n");
#if DEBUG
        print_objid(var->name, var->name_length);
        print_objid(custom_name, custom_name_len);
#endif
        return 0;
    }
    return 1;
}

int custom_get_next(netsnmp_variable_list *var, oid *out_name, size_t *out_length) {
    if (storage->n_custom == 0) {
        return -1;
    }

    CustomEntry_t *entry;
    if (snmp_oid_compare(var->name, var->name_length, custom_name, custom_name_len) <= 0) {
        // var is before custom
        entry = &storage->custom[0];
    } else if (custom_is_var(var)) {
        int next;
        uint8_t key[KEY_LEN];
        custom_oid_to_key(key, &var->name[custom_name_len], var->name_length - custom_name_len);
        custom_find_entry(key, KEY_LEN, &next);
        if (next == -1) {
            return -1;
        }
        entry = &storage->custom[next];
    } else {
        return -1;
    }
    memcpy(out_name, custom_name, sizeof(oid) * custom_name_len);
    size_t add_length;
    custom_key_to_oid(entry->key, out_name + custom_name_len, &add_length);
    *out_length = custom_name_len + add_length;
    return 0;
}

void custom_get(netsnmp_variable_list *var, int *errstat) {
    uint8_t key[KEY_LEN];
    custom_oid_to_key(key, &var->name[custom_name_len], var->name_length - custom_name_len);
    int entry = custom_find_entry(key, KEY_LEN, NULL);
    if (entry == -1) {
        hsnmp_set_var_nosuchinstance(var);
        return;
    }
    var->type = ASN_OCTET_STR;
    if (snmp_set_var_value(var, storage->custom[entry].text, storage->custom[entry].length) != 0) {
        hsnmp_set_var_null(var);
        *errstat = SNMP_ERR_RESOURCEUNAVAILABLE;
    }
}

void custom_set(netsnmp_variable_list *var, int *errstat) {
    if (var->type != ASN_OCTET_STR) {
        *errstat = SNMP_ERR_WRONGTYPE;
        return;
    }
    if (var->val_len > CUSTOM_MAX_LEN) {
        *errstat = SNMP_ERR_TOOBIG;
        return;
    }
    uint8_t key[KEY_LEN];
    custom_oid_to_key(key, &var->name[custom_name_len], var->name_length - custom_name_len);

    DBG_PRINTF("custom_set write to: ");
#ifdef DEBUG
    for (int i = 0; i < KEY_LEN; i++) {
        fprintf(stderr, "%02x", key[i]);
    }
    fprintf(stderr, "\n");
#endif

    int entry = custom_find_entry(key, KEY_LEN / 2, NULL);
    if (entry != -1) {
        DBG_PRINTF("custom_set trying to write existing value\n");
        *errstat = SNMP_ERR_NOACCESS;
        return;
    }
    entry = custom_add_entry(key);
    if (entry == -1) {
        *errstat = SNMP_ERR_NOCREATION;
        return;
    }

    if(custom_entry_create(&storage->custom[entry], var->val.string, var->val_len) != 0) {
        *errstat = SNMP_ERR_NOCREATION;
        return;
    }
}

