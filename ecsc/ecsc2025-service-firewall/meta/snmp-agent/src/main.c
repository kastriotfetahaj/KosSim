#include <arpa/inet.h>
#include <asm-generic/errno-base.h>
#include <assert.h>
#include <errno.h>
#include <netdb.h>
#include <netinet/in.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#include "general.h"
#include "pdu_handling.h"
#include "storage.h"
#include "user_monitoring.h"

#ifdef FUZZING
__AFL_FUZZ_INIT()
#endif

uint8_t packet_buf[MAX_PACKET_SIZE];
char auth_community_str[COMMUNITY_MAX_LEN];

struct pg_work_queue pg_queue;
static pthread_t pg_workers[PG_WORKERS];

static int do_exit = 0;

void error(char *msg) {
    fprintf(stderr, "%s\n", msg);
    exit(EXIT_FAILURE);
}

void error_no(char *msg) {
    perror(msg);
    exit(EXIT_FAILURE);
}

static void shutdown_handler(int signo, siginfo_t *info, void *context) {
    // ignore unused parameters
    (void)signo; (void)info; (void)context;

    fprintf(stderr, "Recieved signal, terminating...\n");
    do_exit = 1;
}

void periodic_actions(void) {
    // execute periodic actions based on a time interval
    // will only execute actions while packets are processed
    static time_t last_custom_cleanup = 0;
    if (time(NULL) - CUSTOM_CLEANUP_INTERVAL > last_custom_cleanup) {
        clean_custom_entries();
        last_custom_cleanup = time(NULL);
    }
}

#ifdef FUZZING
int fuzzing_main(void) {
#ifdef __AFL_HAVE_MANUAL_CONTROL
    __AFL_INIT();
#endif

    unsigned char *buf = __AFL_FUZZ_TESTCASE_BUF;
    while (__AFL_LOOP(10000)) {
        // don't use the macro directly in a call!
        int len = __AFL_FUZZ_TESTCASE_LEN;
        unsigned char *ptr = buf;
        while (len - 2 > 0) {
            int single_len = *(uint16_t*)ptr;
            if (single_len > len - 2) {
                single_len = len - 2;
            }
            ptr += 2;
            handle_packet(0, NULL, 0, ptr, single_len);
            ptr += single_len;
            len = len - (single_len + 2);
        }
        // clear storage after each input
        custom_reset();
    }
    return 0;
}
#endif

int main(void) {
    // get the SNMP authenticated community string
    char *auth_str = getenv("SNMP_AUTH_COMMUNITY");
    char *auth_path = getenv("SNMP_AUTH_COMMUNITY_FILE");
    if (auth_str != NULL) {
        strncpy(auth_community_str, auth_str, sizeof(auth_community_str));
    } else if (auth_path != NULL) {
        FILE *auth_file = fopen(auth_path, "r");
        if (auth_file == NULL) {
            error_no("fopen()");
        }
        if (fgets(auth_community_str, sizeof(auth_community_str) - 1, auth_file) == NULL) {
            error_no("fgets()");
        }
        if (fclose(auth_file) != 0) {
            error_no("fclose()");
        }
    } else {
        error("Missing either SNMP_AUTH_COMMUNITY or SNMP_AUTH_COMMUNITY_FILE environment variable");
    }

    // initialize storage modules
    if (init_storage() != 0) {
        error("Init storage failed");
    }

    // initialize SNMP
    netsnmp_init_mib();
    init_snmp("firewall");

    if (custom_init() == -1 || monitoring_init() == -1 || user_monitoring_init() == -1) {
        error("Init SNMP modules failed");
    }

#ifndef FUZZING
    // initialize database monitoring
    if (pg_work_queue_init(&pg_queue, PG_QUEUE_SIZE) != 0) {
        error("pg_work_queue_init()");
    }
    for (int i = 0; i < PG_WORKERS; i++) {
        if(pg_spawn_worker(pg_workers + i, &pg_queue) != 0) {
            error("pg_spawn_worker()");
        }
    }
#endif

    struct sigaction handle_shutdown = { 0 };
    handle_shutdown.sa_flags = SA_SIGINFO;
    handle_shutdown.sa_sigaction = &shutdown_handler;
    if (sigaction(SIGINT, &handle_shutdown, NULL) == -1) {
        error_no("sigaction()");
    }
    if (sigaction(SIGTERM, &handle_shutdown, NULL) == -1) {
        error_no("sigaction()");
    }

#ifdef FUZZING
    return fuzzing_main();
#else
    int sock = socket(AF_INET6, SOCK_DGRAM, 0);
    if (sock < 0) {
        error_no("socket()");
    }

    int optval = 1;
    if (setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &optval, sizeof(optval)) == -1) {
        error_no("setsockopt()");
    }

    struct sockaddr_in6 serveraddr;
    bzero(&serveraddr, sizeof(serveraddr));
    serveraddr.sin6_family = AF_INET6;
    serveraddr.sin6_addr = in6addr_any;
    serveraddr.sin6_port = htons(1161);

    if (bind(sock, (struct sockaddr *)&serveraddr, sizeof(serveraddr)) < 0) {
        error_no("bind()");
    }

    struct sockaddr_in6 clientaddr;
    socklen_t clientlen = sizeof(clientaddr);

    fprintf(stderr, "Agent startup completed. Serving requests...\n");
    while (!do_exit) {
        bzero(packet_buf, MAX_PACKET_SIZE);
        ssize_t n = recvfrom(sock, packet_buf, MAX_PACKET_SIZE, 0, (struct sockaddr *)&clientaddr, &clientlen);
        if (n < 0) {
            if (errno == EINTR) {
                // retry on interrupt
                // might exit if this was caused by SIGINT/SIGTERM
                continue;
            }
            error_no("recvfrom()");
        }
        handle_packet(sock, &clientaddr, clientlen, packet_buf, n);
        periodic_actions();
    }

    fprintf(stderr, "Last packet processed, stopping pg workers\n");
    pg_work_queue_shutdown(&pg_queue);
    for (int i = 0; i < PG_WORKERS; i++) {
        pthread_join(pg_workers[i], NULL);
    }
    pg_work_queue_destroy(&pg_queue);
    if (msync(storage, sizeof(struct Storage), MS_SYNC) == -1) {
        fprintf(stderr, "msync failed, storage may be corrupted\n");
    }
    fprintf(stderr, "Shutdown successfull\n");
#endif
}
