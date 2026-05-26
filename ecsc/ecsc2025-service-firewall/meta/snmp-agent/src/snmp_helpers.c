#include "snmp_helpers.h"

int hsnmp_set_var_null(netsnmp_variable_list *var) {
    return snmp_set_var_typed_value(var, ASN_NULL, NULL, 0);
}

int hsnmp_set_var_nosuchobject(netsnmp_variable_list *var) {
    return snmp_set_var_typed_value(var, SNMP_NOSUCHOBJECT, NULL, 0);
}

int hsnmp_set_var_nosuchinstance(netsnmp_variable_list *var) {
    return snmp_set_var_typed_value(var, SNMP_NOSUCHINSTANCE, NULL, 0);
}
