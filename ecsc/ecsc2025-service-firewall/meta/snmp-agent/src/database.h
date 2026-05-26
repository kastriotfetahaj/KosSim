#include <pthread.h>
#include <stdint.h>
#include <netinet/in.h>
#include "general.h"

enum pg_query_identifier {
    // User-independent queries.
    QUERY_SOCKET_SERVER_ADDR,
    QUERY_SOCKET_CLIENT_ADDR,
    QUERY_DB_SERVER_ADDR,
    QUERY_DB_CLIENT_ADDR,
    QUERY_DB_NAME_HASH,
    QUERY_DB_SESSION_USER_HASH,
    QUERY_DB_SYSTEM_USER_HASH,
    QUERY_DB_ACTIVE_USERS,
    QUERY_DB_FREE_IP_RANGES,

    // Per-user queries.
    QUERY_DB_USER_DROPPED_PACKETS,
    QUERY_DB_USER_DROPPED_BYTES,

    // This is the number of user-independent queries that we can make for bookkeeping.
    __QUERY_DB_COUNT = QUERY_DB_FREE_IP_RANGES + 1,

    // This is the number of queries in total
    __QUERY_ALL_COUNT = QUERY_DB_USER_DROPPED_BYTES + 1,
};

struct pg_work_item {
    uint64_t user_identifier;
    uint32_t query_identifier;
    int socket;
    struct sockaddr_in6 client;
    netsnmp_pdu *pdu;
};

struct pg_work_queue {
    struct pg_work_item *ring;
    volatile uint32_t head, tail, shutdown;
    uint32_t capacity;
    pthread_mutex_t mutex;
    pthread_cond_t cond;
};

extern struct pg_work_queue pg_queue;

int pg_work_queue_init(struct pg_work_queue *queue, uint32_t capacity);
int pg_work_queue_get(struct pg_work_queue *queue, struct pg_work_item *out, int timeout_seconds);
int pg_work_queue_try_put(struct pg_work_queue *queue, struct pg_work_item in);
void pg_work_queue_shutdown(struct pg_work_queue *queue);
void pg_work_queue_destroy(struct pg_work_queue *queue);

int pg_spawn_worker(pthread_t *thread, struct pg_work_queue *queue);
