#include <sys/types.h>
#include <net-snmp/net-snmp-config.h>
#include <net-snmp/net-snmp-includes.h>
#include <stdint.h>
#include "debug.h"

#define MAX_PACKET_SIZE 2048
#define PG_QUEUE_SIZE 100
#define PG_WORKERS 5
#define COMMUNITY_STR "firewall"

extern char auth_community_str[COMMUNITY_MAX_LEN];
