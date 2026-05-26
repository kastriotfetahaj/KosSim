#include <netdb.h>
#include <string.h>
#include <unistd.h>

#include "pdu_handling.h"
#include "snmp_helpers.h"
#include "storage_custom.h"
#include "storage_monitoring.h"
#include "user_monitoring.h"

int parse(netsnmp_pdu *pdu, uint8_t *data, size_t length, int *errstat) {
    uint8_t community[COMMUNITY_MAX_LEN];
    size_t community_length = COMMUNITY_MAX_LEN;
    *errstat = SNMP_ERR_GENERR;

    if (pdu == NULL) {
        printf("Warning: out of memory\n");
        *errstat = SNMP_ERR_RESOURCEUNAVAILABLE;
        return -1;
    }

    pdu->transid = snmp_get_next_transid();
    data = snmp_comstr_parse(data, &length, community, &community_length, &pdu->version);
    if (data == NULL) {
        *errstat = SNMP_ERR_BADVALUE;
        return -1;
    }
    if (pdu->version != SNMP_VERSION_2c) {
        *errstat = SNMP_ERR_BADVALUE;
        return -1;
    }

    pdu->community = netsnmp_memdup(community, community_length);
    if (pdu->community == NULL) {
        *errstat = SNMP_ERR_RESOURCEUNAVAILABLE;
        return -1;
    }
    pdu->community_len = community_length;

    // ignore authentication for fuzzing
#ifndef FUZZING
    if (
        (community_length != strlen(COMMUNITY_STR) || memcmp(&community, COMMUNITY_STR, community_length) != 0) &&
        (community_length != strlen(auth_community_str) || memcmp(&community, auth_community_str, community_length))
        ) {
        *errstat = SNMP_ERR_AUTHORIZATIONERROR;
        return -1;
    }
#endif
    if (snmp_pdu_parse(pdu, data, &length) != 0) {
        *errstat = SNMP_ERR_BADVALUE;
        return -1;
    }
    *errstat = SNMP_ERR_NOERROR;
    return 0;
}

void send_response(int sock, struct sockaddr_in6 *clientaddr, socklen_t clientlen, netsnmp_pdu *pdu) {
    int rc;
    netsnmp_session session;
    uint8_t *buf, *pkt;

    buf = malloc(MAX_PACKET_SIZE);
    if (buf == NULL) {
        printf("Warning: out of memory\n");
        return;
    }

    bzero(&session, sizeof(session));
    pdu->command = SNMP_MSG_RESPONSE;
    pdu->version = SNMP_VERSION_2c;

    size_t buf_len = MAX_PACKET_SIZE, offset = 0;
    rc = snmp_build(&buf, &buf_len, &offset, &session, pdu);
    if (rc != 0) {
        free(buf);
        return;
    }
    DBG_PRINTF("Build pdu: buf_len: %lu offset: %lu\n", buf_len, offset);
    pkt = buf + buf_len - offset;

#if DEBUG
    DBG_PRINTF("Outgoing packet data: ");
    for (size_t i = 0; i < offset; i++) {
        fprintf(stderr, "%02x ", pkt[i]);
    }
    fprintf(stderr, "\n");
#endif

#ifndef FUZZING
    ssize_t n = sendto(sock, pkt, offset, 0, (struct sockaddr *)clientaddr, clientlen);
    if (n < 0) {
        perror("sendto() failed");
    }
#endif
    free(buf);
}

void handle_get(netsnmp_variable_list *vars, int *errstat, struct pg_work_item *pg_work) {
    while (vars && pg_work->query_identifier == 0) {
        if (monitoring_is_var(vars)) {
            monitoring_get(vars, errstat);
        } else if (user_monitoring_is_var(vars)) {
            user_monitoring_get(vars, errstat, pg_work);
        } else if (custom_is_var(vars)) {
            custom_get(vars, errstat);
        } else {
            hsnmp_set_var_nosuchobject(vars);
        }
        vars = vars->next_variable;
    }
}

int handle_getnext(netsnmp_variable_list *vars, int *errstat) {
    oid name[MAX_OID_LEN];
    size_t name_length = MAX_OID_LEN;

    if (vars == NULL) {
        return -1;
    }

    // try to find next
    if (monitoring_getnext(vars, name, &name_length) != 0 &&
        user_monitoring_getnext(vars, name, &name_length) != 0 &&
        custom_get_next(vars, name, &name_length) != 0) {
        snmp_set_var_typed_value(vars, SNMP_ENDOFMIBVIEW, NULL, 0);
        return -1;
    }

    if (snmp_set_var_objid(vars, name, name_length) != 0 ||
        snmp_set_var_typed_value(vars, ASN_NULL, NULL, 0) != 0) {
        *errstat = SNMP_ERR_GENERR;
        return -1;
    }
    return 0;
}

void handle_set(netsnmp_variable_list *vars, int *errstat) {
    while (vars) {
        if (monitoring_is_var(vars)) {
            monitoring_set(vars, errstat);
        } else if (user_monitoring_is_var(vars)) {
            user_monitoring_set(vars, errstat);
        } else if (custom_is_var(vars)) {
            custom_set(vars, errstat);
        } else {
            hsnmp_set_var_nosuchobject(vars);
        }
        vars = vars->next_variable;
    }
}

void handle_pdu(netsnmp_pdu *pdu, int *errstat, struct pg_work_item *pg_work) {
    netsnmp_variable_list *vars = pdu->variables;
    switch (pdu->command) {
        case SNMP_MSG_GETNEXT:
        case SNMP_MSG_GETBULK:
            if (handle_getnext(vars, errstat) != 0) {
                return;
            }
        case SNMP_MSG_GET:
            handle_get(vars, errstat, pg_work);
            pdu->variables = vars;
            break;
        case SNMP_MSG_SET:
            // ignore authentication for fuzzing
#ifndef FUZZING
            if (pdu->community_len != strlen(auth_community_str) || memcmp(pdu->community, auth_community_str, pdu->community_len)) {
                *errstat = SNMP_ERR_NOACCESS;
                break;
            }
#endif
            handle_set(vars, errstat);
            pdu->variables = vars;
            break;
        default:
            *errstat = SNMP_ERR_BADVALUE;
    }
}

void handle_packet(int sock, struct sockaddr_in6 *clientaddr, socklen_t clientlen, uint8_t *buf, ssize_t len) {
    int errstat, rc;
#if DEBUG
    {
        char name[INET6_ADDRSTRLEN];
        getnameinfo((struct sockaddr*)clientaddr, clientlen, name, sizeof(name), NULL, 0, NI_NUMERICHOST);
        DBG_PRINTF("Got connection from: %s\n", name);
        DBG_PRINTF("Raw address:");
        for (uint32_t i = 0; i < sizeof(clientaddr->sin6_addr); i++) {
            fprintf(stderr, "%02x ", clientaddr->sin6_addr.s6_addr[i]);
        }
        fprintf(stderr, "\n");
        DBG_PRINTF("Raw Packet:");
        for (uint32_t i = 0; i < len; i++) {
            fprintf(stderr, "%02x ", buf[i]);
        }
        fprintf(stderr, "\n");
    }
#endif
    struct pg_work_item pg_work = { 0 };
    int do_send_response = TRUE;
    netsnmp_pdu *pdu = SNMP_MALLOC_TYPEDEF(netsnmp_pdu);
    if (pdu == NULL) {
        printf("Warning: out of memory\n");
        return;
    }
    rc = parse(pdu, buf, len, &errstat);

#if DEBUG
    DBG_PRINTF("version: %ld command: %s flags: %lu ", pdu->version, snmp_pdu_type(pdu->command), pdu->flags);
    DBG_PRINTF("community: %.*s\n", (int)pdu->community_len, pdu->community);

    if (pdu->variables) {
        print_variable(pdu->variables->name, pdu->variables->name_length, pdu->variables);
    }
    fflush(stdout);
#endif

    if (rc == 0) {
        handle_pdu(pdu, &errstat, &pg_work);
    }

#ifndef FUZZING
    if (pg_work.user_identifier != 0) {
        pg_work.socket = sock;
        pg_work.client = *clientaddr;
        pg_work.pdu = pdu;
        DBG_PRINTF("Sending pg_work to queue. query: %x query_identifier %lx\n", pg_work.query_identifier, pg_work.user_identifier);
        if (pg_work_queue_try_put(&pg_queue, pg_work) != 0) {
            errstat = SNMP_ERR_RESOURCEUNAVAILABLE;
        } else {
            do_send_response = FALSE;
        }
    }
#endif

    pdu->errstat = errstat;
    if (do_send_response) {
        // if no response is send the pdu must bee freed by the worker
        send_response(sock, clientaddr, clientlen, pdu);
        snmp_free_pdu(pdu);
    }
}

