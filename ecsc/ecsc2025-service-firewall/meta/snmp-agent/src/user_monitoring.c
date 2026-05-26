#include "user_monitoring.h"
#include "snmp_helpers.h"

#define IDENTIFIER_LEN 8

oid user_monitoring_name[MAX_OID_LEN];
size_t user_monitoring_name_len = MAX_OID_LEN;
oid user_monitoring_end_name[MAX_OID_LEN];
size_t user_monitoring_end_name_len = MAX_OID_LEN;

uint64_t user_monitoring_oid_to_identifier(oid *name) {
    uint64_t identifier = 0;
    for (size_t i = 0; i < IDENTIFIER_LEN; i++) {
        identifier = (identifier << 8) | (name[i] & 0xFF);
    }
    return identifier;
}


int user_monitoring_init(void) {
    if (snmp_parse_oid("userMonitoringEntry", user_monitoring_name, &user_monitoring_name_len) == NULL) {
        printf("Couldn't parse oid %s\n", "userMonitoringEntry");
        return -1;
    }
    if (snmp_parse_oid("userMonitoringEnd", user_monitoring_end_name, &user_monitoring_end_name_len) == NULL) {
        printf("Couldn't parse oid %s\n", "userMonitoringEnd");
        return -1;
    }
    return 0;
}

int user_monitoring_is_var(netsnmp_variable_list *var) {
    if (var->name_length != user_monitoring_name_len + 1 + IDENTIFIER_LEN) {
        DBG_PRINTF("user_monitoring_is_var name length mismatch: %zu vs %zu\n", var->name_length, user_monitoring_name_len + 1 + IDENTIFIER_LEN);
        return 0;
    }
    if (snmp_oid_compare(var->name, user_monitoring_name_len, user_monitoring_name, user_monitoring_name_len) != 0) {
        DBG_PRINTF("user_monitoring_is_var name mismatch\n");
#if DEBUG
        print_objid(var->name, var->name_length);
        print_objid(user_monitoring_name, user_monitoring_name_len);
#endif
        return 0;
    }
    return 1;
}

int user_monitoring_getnext(netsnmp_variable_list *var, oid *out_name, size_t *out_length) {
    if (snmp_oid_compare(var->name, var->name_length, user_monitoring_name, user_monitoring_name_len) <= 0) {
        // var is before user monitoring
        // can't know the identifier
        return -1;
    } else if (user_monitoring_is_var(var)) {
        memcpy(out_name, user_monitoring_name, sizeof(oid) * var->name_length);
        out_name[user_monitoring_name_len] = var->name[user_monitoring_name_len] + 1;
        *out_length = var->name_length;
        if (snmp_oid_compare(out_name, *out_length, user_monitoring_end_name, user_monitoring_end_name_len) >= 0) {
            // past the last valid value
            return -1;
        }
        return 0;
    } else {
        return -1;
    }
}

void user_monitoring_get(netsnmp_variable_list *var, int *errstat, struct pg_work_item *pg_work) {
    pg_work->query_identifier = var->name[user_monitoring_name_len];
    if (pg_work->query_identifier == UINT_MAX) {
        pg_work->query_identifier = 0;
        *errstat = SNMP_ERR_GENERR;
        return;
    }
    pg_work->user_identifier = user_monitoring_oid_to_identifier(var->name + user_monitoring_name_len + 1);
}

void user_monitoring_set(netsnmp_variable_list *var, int *errstat) {
    hsnmp_set_var_null(var);
    *errstat = SNMP_ERR_NOTWRITABLE;
}
