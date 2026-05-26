#include "snmp_helpers.h"
#include "storage.h"

oid monitoring_name[MAX_OID_LEN];
size_t monitoring_name_len = MAX_OID_LEN;
oid monitoring_end_name[MAX_OID_LEN];
size_t monitoring_end_name_len = MAX_OID_LEN;

int monitoring_init(void) {
    if (snmp_parse_oid("monitoring", monitoring_name, &monitoring_name_len) == NULL) {
        printf("Couldn't parse oid %s\n", "monitoring");
        return -1;
    }
    if (snmp_parse_oid("monitoringEnd", monitoring_end_name, &monitoring_end_name_len) == NULL) {
        printf("Couldn't parse oid %s\n", "monitoringEnd");
        return -1;
    }
    return 0;
}

int monitoring_is_var(netsnmp_variable_list *var) {
    if (var->name_length != monitoring_name_len + 1) {
        return 0;
    }
    if (snmp_oid_compare(var->name, var->name_length - 1, monitoring_name, monitoring_name_len) != 0) {
        return 0;
    }
    return 1;
}

int monitoring_getnext(netsnmp_variable_list *var, oid *out_name, size_t *out_length) {
    if (snmp_oid_compare(var->name, var->name_length, monitoring_name, monitoring_name_len) <= 0) {
        // var is before monitoring
        memcpy(out_name, monitoring_name, sizeof(oid) * monitoring_name_len);
        out_name[monitoring_name_len] = 0;
        *out_length = monitoring_name_len + 1;
        return 0;
    } else if (monitoring_is_var(var)) {
        memcpy(out_name, monitoring_name, sizeof(oid) * monitoring_name_len);
        out_name[monitoring_name_len] = var->name[monitoring_name_len] + 1;
        *out_length = monitoring_name_len + 1;
        if (snmp_oid_compare(out_name, *out_length, monitoring_end_name, monitoring_end_name_len) >= 0) {
            return -1;
        }
        return 0;
    } else {
        return -1;
    }
}

void monitoring_get(netsnmp_variable_list *var, int *errstat) {
    var->type = ASN_COUNTER64;
    uint64_t idx = var->name[monitoring_name_len];
    uint64_t val = storage->monitoring[idx];
    struct counter64 cntr;
    cntr.low = (uint32_t)val;
    cntr.high = val >> 32;
    if (snmp_set_var_value(var, &cntr, sizeof(cntr)) != 0) {
        hsnmp_set_var_null(var);
        *errstat = SNMP_ERR_RESOURCEUNAVAILABLE;
    }
}

void monitoring_set(netsnmp_variable_list *var, int *errstat) {
    hsnmp_set_var_null(var);
    *errstat = SNMP_ERR_NOTWRITABLE;
}
