#include "general.h"

enum monitoring_indices {
    MON_DB_SOCKET_IPV4,
    MON_DB_SOCKET_IPV6_HIGH,
    MON_DB_SOCKET_IPV6_LOW,
    MON_DB_SOCKET_PORT,
    MON_SNMP_SOCKET_IPV4,
    MON_SNMP_SOCKET_IPV6_HIGH,
    MON_SNMP_SOCKET_IPV6_LOW,
    MON_DB_IPV4,
    MON_DB_IPV6_HIGH,
    MON_DB_IPV6_LOW,
    MON_SNMP_IPV4,
    MON_SNMP_IPV6_HIGH,
    MON_SNMP_IPV6_LOW,
    MON_DB_NAME_HASH,
    MON_DB_USER_HASH,
    MON_DB_SYSUSER_HASH,
    MON_STATS_USERS,
    MON_STATS_FREE_IP_RANGES,
    N_MONITORING_VALUES,
};

int monitoring_init(void);
int monitoring_is_var(netsnmp_variable_list *var);
int monitoring_getnext(netsnmp_variable_list *var, oid *out_name, size_t *out_length);
void monitoring_get(netsnmp_variable_list *var, int *errstat);
void monitoring_set(netsnmp_variable_list *var, int *errstat);
