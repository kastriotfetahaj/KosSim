#include "database.h"
#include "general.h"

int user_monitoring_init(void);
int user_monitoring_is_var(netsnmp_variable_list *var);
int user_monitoring_getnext(netsnmp_variable_list *var, oid *out_name, size_t *out_length);
void user_monitoring_get(netsnmp_variable_list *var, int *errstat, struct pg_work_item *pg_work);
void user_monitoring_set(netsnmp_variable_list *var, int *errstat);
