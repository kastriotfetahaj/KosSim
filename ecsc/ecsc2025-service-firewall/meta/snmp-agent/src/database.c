// This is a custom implementation to
//  - enforce the use of trust authentication for the anonymous user (no "set a password" defense to fix all bugs)
//  - somewhat obfuscate the statistics queries we do (no "change the database IP" defense to hinder exploitation)

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <openssl/err.h>
#include <openssl/rand.h>
#include <openssl/ssl.h>
#include <openssl/tls1.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#include "database.h"
#include "pdu_handling.h"
#include "storage.h"

#ifdef DEBUG
#define pg_log stderr
#else
#define pg_log NULL
#endif

struct pg_session {
    int tcp_socket;
    SSL_CTX *context;
    SSL *ssl;
};

struct __attribute__((packed)) pg_message {
    char message_type;
    uint32_t content_length;
    char payload[];
};

enum pg_query_result {
    PG_SUCCESS,
    PG_NETWORK_ERROR,
    PG_DB_ERROR,
    PG_UNEXPECTED,
    PG_NULL,
};
#define PG_IS_OK(res) ({ enum pg_query_result _res = (res); _res == PG_SUCCESS || _res == PG_NULL; })

static unsigned int pg_random(void) {
    unsigned int value = 0;
    RAND_bytes((unsigned char *) &value, sizeof(value));
    return value;
}

__attribute__((pure))
static size_t pg_message_size(const struct pg_message *message) {
    return (size_t) ntohl(message->content_length) + offsetof(struct pg_message, content_length);
}

__attribute__((pure))
static inline int pg_message_is_error(const void *buffer) {
    return ((const struct pg_message *) buffer)->message_type == 'E';
}

__attribute__((format(printf, 1, 2)))
static inline void pg_error(const char *format, ...) {
    if (pg_log) {
        va_list args;
        va_start(args, format);
        vfprintf(pg_log, format, args);
        fprintf(pg_log, "\n");
        va_end(args);
    }
}

__attribute__((format(printf, 1, 2)))
static inline void pg_perror(const char *format, ...) {
    if (pg_log) {
        int saved_errno = errno;
        va_list args;
        va_start(args, format);
        vfprintf(pg_log, format, args);
        if (saved_errno) {
            errno = saved_errno;
            fprintf(pg_log, ": %m\n");
        } else {
            fprintf(pg_log, "\n");
        }
        va_end(args);
    }
}

__attribute__((format(printf, 1, 2)))
static inline void pg_ossl_perror(const char *format, ...) {
    if (pg_log) {
        va_list args;
        va_start(args, format);
        vfprintf(pg_log, format, args);
        fprintf(pg_log, ": ");
        ERR_print_errors_fp(pg_log);
        va_end(args);
    }
}

__attribute__((format(printf, 1, 3)))
static inline void pg_pgsql_perror(const char *format, const void *buffer, ...) {
    if (pg_log) {
        va_list args;
        va_start(args, buffer);
        vfprintf(pg_log, format, args);
        va_end(args);
        fprintf(pg_log, ": ");

        const struct pg_message *message = buffer;
        if (ntohl(message->content_length) < 5) {
            fprintf(pg_log, "incomplete error message\n");
            return;
        }

        uint32_t cursor = 0;
        while (cursor < ntohl(message->content_length) - 4) {
            char field_type = message->payload[cursor];
            const char *data = &message->payload[cursor + 1];
            if (!field_type)
                break;

            // Lots of data in this, we only really want 'M', the primary error message.
            if (field_type == 'M')
                fprintf(pg_log, "%s", data);

            cursor += strlen(data) + 1;
        }
        fprintf(pg_log, "\n");
    }
}

__attribute__((section(".rodata.hidden"))) static const unsigned char OBF_ALPN[] = {
    10, 'p', 'o', 's', 't', 'g', 'r', 'e', 's', 'q', 'l'
};

static const char *SNI = "db";

static const char *CA = "/state/firewall/tls/ca.crt";

#define TIMEOUT_SECONDS 5

#define compile_time_htons(value) ((((value) & 0xff) << 8) | (((value) & 0xff00) >> 8))
#define compile_time_htonl(value) ((((value) & 0xff) << 24) | (((value) & 0xff00) << 8) | \
                                   (((value) & 0xff0000) >> 8) | (((value) & 0xff000000) >> 24))

static const struct sockaddr_in6 SERVER_IPV6 = {
    .sin6_family = AF_INET6,
    .sin6_addr = (struct in6_addr) {
        .s6_addr = {
            // fd00:ec5c::3
            0xfd, 0x00, 0xec, 0x5c,
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x03,
        }
    },
    .sin6_port = compile_time_htons(5432),
    .sin6_flowinfo = 0,
    .sin6_scope_id = 0,
};

static const struct sockaddr_in SERVER_IPV4 = {
    .sin_family = AF_INET,
    .sin_addr = (struct in_addr) {
        // 10.0.0.3
        .s_addr = compile_time_htonl(0x0a000003),
    },
    .sin_port = compile_time_htons(5432),
};

__attribute__((section(".rodata.hidden"))) static const char OBF_PGSQL_STARTUP[] =
    // Header (length of the entire packet)
    "\x00\x00\x00\x2a"
    // Protocol options
    "\x00\x03" // Major version (3)
    "\x00\x00" // Minor version (0)
    // Connection options
    "user\0" "anonymous\0"
    "database\0" "firewall\0"
    "\0"
;

__attribute__((always_inline))
static inline void pg_reveal(uint8_t *buffer, const char *ciphertext, size_t length) {
    for (size_t i = 0; i < length; ++i) {
        uint8_t byte = (uint8_t) ciphertext[i];
        byte = (byte << 3) | (byte >> 5);
        byte *= 13;
        byte = (byte << 3) | (byte >> 5);
        byte *= 37;
        byte = (byte << 3) | (byte >> 5);
        buffer[i] = byte;
        // TODO: Not sure what is going on here. But the compiler seems to do weird things unless I
        // convince it (by print/somehow else) that `byte` is used somewhere. Might be UB in some
        // other place, but UBSAN doesn't want to tell me and neither does my host clang.
        __asm__ volatile ("" :: "r"(byte) : "memory");
    }
}
#define OBF_MAX_LEN 128
#define PG_SEND_REVEALED(session, buffer, query) \
    ({ \
        _Static_assert(sizeof(buffer) >= sizeof(query) - 1, "buffer is too small to reveal query"); \
        pg_reveal((uint8_t *) &buffer[0], query, sizeof(query) - 1); \
        SSL_write((session)->ssl, buffer, sizeof(query) - 1); \
    })

static void pg_tls_disconnect(struct pg_session *session) {
    int shutdown = SSL_shutdown(session->ssl);
    if (shutdown < 0) {
        pg_ossl_perror("failed to shut down TLS connection");
    } else if (shutdown == 0) {
        char buffer[512];
        int returned;
        while ((returned = SSL_read(session->ssl, buffer, sizeof(buffer))) > 0);
        if (SSL_get_error(session->ssl, returned) != SSL_ERROR_ZERO_RETURN)
            pg_ossl_perror("failed to clear TLS connection during shutdown");
    }
    SSL_free(session->ssl);
    if (close(session->tcp_socket))
        pg_perror("failed to close socket");
    SSL_CTX_free(session->context);
}

static void pg_ssl_key_log_callback(const SSL *__attribute__((unused)) ssl, const char *line) {
    static FILE *ssl_key_log_file = NULL;

    if (!ssl_key_log_file) {
        const char *path = getenv("SSLKEYLOGFILE");
        if (!path) {
            pg_error("SSLKEYLOGFILE was configured but is no longer set");
            return;
        }
        if (!(ssl_key_log_file = fopen(path, "a"))) {
            pg_perror("failed to open SSLKEYLOGFILE %s", path);
            return;
        }
    }

    fprintf(ssl_key_log_file, "%s\n", line);
    fflush(ssl_key_log_file);
}

static int pg_tls_connect(struct pg_session *session, const struct sockaddr *addr, socklen_t addr_len) {
    uint8_t buffer[OBF_MAX_LEN];
    memset(session, 0, sizeof(*session));

    // Create the SSL context
    session->context = SSL_CTX_new(TLS_client_method());
    if (!session->context) {
        pg_ossl_perror("failed to create TLS context");
        return -1;
    }

    if (getenv("SSLKEYLOGFILE"))
        SSL_CTX_set_keylog_callback(session->context, pg_ssl_key_log_callback);

    if (SSL_CTX_load_verify_locations(session->context, CA, NULL) != 1) {
        pg_ossl_perror("failed to load CA certificate");
        goto cleanup_context;
    }

    pg_reveal(buffer, (const char*)OBF_ALPN, sizeof(OBF_ALPN));
    if (SSL_CTX_set_alpn_protos(session->context, buffer, sizeof(OBF_ALPN))) {
        pg_ossl_perror("failed to set ALPN protocols");
        goto cleanup_context;
    }

    SSL_CTX_set_verify(session->context, SSL_VERIFY_PEER | SSL_VERIFY_FAIL_IF_NO_PEER_CERT, NULL);

    // Create and connect the underlying TCP socket
    session->tcp_socket = socket(addr->sa_family, SOCK_STREAM, 0);
    if (session->tcp_socket < 0) {
        pg_perror("failed to create socket");
        goto cleanup_context;
    }

    struct timeval tv = { .tv_sec = TIMEOUT_SECONDS, .tv_usec = 0 };
    if (setsockopt(session->tcp_socket, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv)) < 0) {
        pg_perror("failed to set receive timeout on socket");
        goto cleanup_socket;
    }

    if (connect(session->tcp_socket, addr, addr_len)) {
        pg_perror("failed to connect to database server");
        goto cleanup_socket;
    }

    // Wrap it in TLS
    session->ssl = SSL_new(session->context);
    if (!session->ssl) {
        pg_ossl_perror("failed to create TLS client structure");
        goto cleanup_socket;
    }

    if (!SSL_set_fd(session->ssl, session->tcp_socket)) {
        pg_ossl_perror("failed to wrap socket");
        goto cleanup_ssl;
    }

    SSL_set_tlsext_host_name(session->ssl, SNI);
    if (!SSL_set1_host(session->ssl, SNI)) {
        pg_ossl_perror("failed to set hostname");
        goto cleanup_ssl;
    }

    // Make the TLS connction
    if (SSL_connect(session->ssl) != 1) {
        pg_ossl_perror("failed to connect to host");
        goto cleanup_ssl;
    }

    return 0;

cleanup_ssl:
    SSL_free(session->ssl);
cleanup_socket:
    if (close(session->tcp_socket))
        pg_perror("failed to close socket");
cleanup_context:
    SSL_CTX_free(session->context);
    return -1;
}

static ssize_t pg_read_message(struct pg_session *session, void *buffer, size_t buffer_size) {
    char *message_buffer = buffer;
    struct pg_message *message = buffer;
    if (buffer_size < sizeof(*message)) {
        pg_error("too small buffer for message header");
        return -1;
    }

    size_t bytes = 0;
    while (bytes < sizeof(*message)) {
        if (SSL_read_ex(session->ssl, &message_buffer[bytes], sizeof(*message) - bytes, &bytes) <= 0) {
            pg_ossl_perror("failed to read message header");
            return -1;
        }
    }

    const size_t full_size = pg_message_size(message);
    if (full_size > buffer_size) {
        pg_error(
            "message of type '%c' and content length %u (%zu bytes in total) is too large for buffer of size %zu",
            message->message_type,
            ntohl(message->content_length),
            full_size,
            buffer_size
        );
    }

    while (bytes < full_size) {
        size_t partial = 0;
        if (SSL_read_ex(session->ssl, &message_buffer[bytes], full_size - bytes, &partial) <= 0) {
            pg_ossl_perror("failed to read message");
            return -1;
        }
        bytes += partial;
    }

    return bytes;
}

static int pg_wait_ready(struct pg_session *session) {
    char response[512];
    ssize_t length;

    // Read messages until we get ReadyForQuery.
    do {
        if ((length = pg_read_message(session, response, sizeof(response))) < 0) {
            pg_error("failed to read message from server");
            return -1;
        }
        if (pg_message_is_error(response)) {
            pg_pgsql_perror("received error from database", response);
            return -1;
        }
    } while (length != 6 || memcmp(response, "Z\x00\x00\x00\x05I", 5));
    return 0;
}

static int pg_connect(struct pg_session *session) {
    char buffer[512] = { 0 };
    ssize_t length;

    // Send the authentication request.
    if (PG_SEND_REVEALED(session, buffer, OBF_PGSQL_STARTUP) <= 0) {
        pg_ossl_perror("failed to send startup command");
        return -1;
    }

    // We expect to get an AuthenticationOk message.
    if ((length = pg_read_message(session, buffer, sizeof(buffer))) < 0) {
        pg_error("authentication failed");
        return -1;
    }
    if (length != 9 || memcmp(buffer, "R\x00\x00\x00\x08\x00\x00\x00\x00", 9)) {
        pg_error("authentication failed");
        return -1;
    }

    return pg_wait_ready(session);
}

static void pg_disconnect(struct pg_session *session) {
    if (SSL_write(session->ssl, "X\x00\x00\x00\x04", 5) <= 0)
        pg_ossl_perror("failed to send termination command");
}


static enum pg_query_result pg_read_and_classify(struct pg_session *session, void *buffer, size_t buffer_size) {
    ssize_t length;
    if ((length = pg_read_message(session, buffer, buffer_size)) < 0) {
        pg_error("failed to read message from server");
        return PG_NETWORK_ERROR;
    }
    if (pg_message_is_error(buffer)) {
        pg_pgsql_perror("received error from database", buffer);
        return PG_DB_ERROR;
    }
    return PG_SUCCESS;
}


int pg_work_queue_init(struct pg_work_queue *queue, uint32_t capacity) {
    pthread_condattr_t attr;
    pthread_condattr_init(&attr);
    if (pthread_condattr_setclock(&attr, CLOCK_MONOTONIC)) {
        pg_error("invalid clock");
        return -1;
    }

    queue->ring = calloc(capacity, sizeof(*queue->ring));
    if (!queue->ring) {
        pthread_condattr_destroy(&attr);
        pg_perror("failed to allocate memory for queue");
        return -1;
    }

    pthread_mutex_init(&queue->mutex, NULL);
    pthread_cond_init(&queue->cond, &attr);
    queue->capacity = capacity;
    queue->head = queue->tail = queue->shutdown = 0;

    pthread_condattr_destroy(&attr);
    return 0;
}

int pg_work_queue_get(struct pg_work_queue *queue, struct pg_work_item *out, int timeout_seconds) {
    int result = 0;
    pthread_mutex_lock(&queue->mutex);
    while (queue->head == queue->tail && !queue->shutdown) {
        struct timespec now;
        if (clock_gettime(CLOCK_MONOTONIC, &now) < 0) {
            pg_perror("failed to get current time");
            result = -1;
            goto unlock;
        }
        now.tv_sec += timeout_seconds;
        if (pthread_cond_timedwait(&queue->cond, &queue->mutex, &now)) {
            // Timed out, just do some updating busywork.
            out->user_identifier = 0;
            out->query_identifier = pg_random() % __QUERY_DB_COUNT;
            out->socket = -1;
            memset(&out->client, 0, sizeof(out->client));
            goto unlock;
        }
    }

    if (queue->shutdown) {
        result = -1;
        goto unlock;
    }

    *out = queue->ring[queue->head];
    queue->head = (queue->head + 1) % queue->capacity;

unlock:
    pthread_mutex_unlock(&queue->mutex);
    return result;
}

int pg_work_queue_try_put(struct pg_work_queue *queue, struct pg_work_item in) {
    pthread_mutex_lock(&queue->mutex);
    uint32_t next = (queue->tail + 1) % queue->capacity;
    if (next == queue->head) {
        pthread_mutex_unlock(&queue->mutex);
        return -1;
    }
    queue->ring[queue->tail] = in;
    queue->tail = next;
    pthread_cond_signal(&queue->cond);
    pthread_mutex_unlock(&queue->mutex);
    return 0;
}

void pg_work_queue_shutdown(struct pg_work_queue *queue) {
    queue->shutdown = 1;
    pthread_cond_broadcast(&queue->cond);
}

void pg_work_queue_destroy(struct pg_work_queue *queue) {
    pthread_mutex_destroy(&queue->mutex);
    pthread_cond_destroy(&queue->cond);
    free(queue->ring);
    memset(queue, 0, sizeof(*queue));
}


__attribute__((section(".rodata.hidden"))) const char OBF_QUERY_DB_SERVER_ADDR[]          = "Q\x00\x00\x00\x1fSELECT inet_server_addr();\0";
__attribute__((section(".rodata.hidden"))) const char OBF_QUERY_DB_CLIENT_ADDR[]          = "Q\x00\x00\x00\x1fSELECT inet_client_addr();\0";
__attribute__((section(".rodata.hidden"))) const char OBF_QUERY_DB_NAME_HASH[]            = "Q\x00\x00\x00\x29SELECT hashtext(current_database());\0";
__attribute__((section(".rodata.hidden"))) const char OBF_QUERY_DB_SESSION_USER_HASH[]    = "Q\x00\x00\x00\x23SELECT hashtext(session_user);\0";
__attribute__((section(".rodata.hidden"))) const char OBF_QUERY_DB_SYSTEM_USER_HASH[]     = "Q\x00\x00\x00\x22SELECT hashtext(system_user);\0";
__attribute__((section(".rodata.hidden"))) const char OBF_GET_FUNCTION_OIDS[]             = "Q\x00\x00\x00\x38SELECT oid, hashtext(proname) FROM stats_functions;\0";

#define BUFFER_SIZE 1024
#define PG_RECEIVE(session, buffer) \
    ({ \
        enum pg_query_result _result = pg_read_and_classify(session, buffer, sizeof(buffer)); \
        if (_result != PG_SUCCESS) \
            return _result; \
        (struct pg_message *) buffer; \
    })

struct __attribute__((packed)) pg_field_data {
    int32_t table_oid;
    int16_t column_attrno;
    int32_t type_oid;
    int16_t type_size;
    int32_t type_modifier;
    int16_t format;
};

#ifdef DEBUG
#define __PG_HEAD(fmt, ...) fmt
#define __PG_TAIL2(fmt, ...) __VA_OPT__(,) __VA_ARGS__
#define __PG_TAIL(...) __PG_TAIL2(__VA_ARGS__, NULL)
#define PG_UNEXPECTED_LOG(...) \
    ({ \
        pg_error("unexpected response from database (at %s:%d): " __PG_HEAD(__VA_ARGS__ __VA_OPT__(,) ""), __FILE__, __LINE__ __PG_TAIL(__VA_ARGS__)); \
        PG_UNEXPECTED; \
    })
#else
#define PG_UNEXPECTED_LOG(...) PG_UNEXPECTED
#endif

static enum pg_query_result pg_read_row_desc(struct pg_session *session, struct pg_field_data *fields, size_t expected_count) {
    char buffer[BUFFER_SIZE] = { 0 };
    struct pg_message *msg;

    msg = PG_RECEIVE(session, buffer);
    uint32_t length = ntohl(msg->content_length);
    if (msg->message_type != 'T')
        return PG_UNEXPECTED_LOG("Message of type '%c' received while waiting for row description ('T')", msg->message_type);
    if (length < 6 || length >= BUFFER_SIZE - 1)
        return PG_UNEXPECTED_LOG("Row description message has bad length %u", msg->message_type);

    int16_t field_count = htons(*(int16_t *) &msg->payload[0]);
    if (field_count < 0 || (size_t) field_count != expected_count)
        return PG_UNEXPECTED_LOG("Expected %zu fields, got %hd", expected_count, field_count);

    char *cursor = &msg->payload[2];
    char *end = &msg->payload[length - 4];

    for (int16_t index = 0; index < field_count; ++index) {
        if (cursor >= end)
            return PG_UNEXPECTED_LOG("Field descriptions too long for buffer");

        cursor += strlen(cursor) + 1; // Skip column name
        if (cursor + sizeof(struct pg_field_data) > end)
            return PG_UNEXPECTED_LOG("Field description for field %hd would be too long for buffer", index);

        struct pg_field_data *pfd = (struct pg_field_data *) cursor;
        fields[index].table_oid = ntohl(pfd->table_oid);
        fields[index].column_attrno = ntohs(pfd->column_attrno);
        fields[index].type_oid = ntohl(pfd->type_oid);
        fields[index].type_size = ntohs(pfd->type_size);
        fields[index].type_modifier = ntohl(pfd->type_modifier);
        fields[index].format = ntohs(pfd->format);
        cursor += sizeof(struct pg_field_data);

        if (fields[index].format < 0 || fields[index].format > 1)
            return PG_UNEXPECTED_LOG("Field %hd has invalid format %hd", index, fields[index].format);
    }
    if (cursor != end)
        return PG_UNEXPECTED_LOG("Did not consume entire row description");
    return PG_SUCCESS;
}

static enum pg_query_result pg_read_int4(struct pg_session *session, int32_t *value) {
    char buffer[BUFFER_SIZE] = { 0 };
    struct pg_message *msg;
    struct pg_field_data field;
    enum pg_query_result result;

    if ((result = pg_read_row_desc(session, &field, 1)) != PG_SUCCESS)
        return result;

    if (field.table_oid != 0 || field.column_attrno != 0 || field.type_oid != 23 || field.type_size != 4 || field.type_modifier != -1)
        return PG_UNEXPECTED_LOG("Unexpected field description (expected int4)");

    msg = PG_RECEIVE(session, buffer);
    uint32_t length = ntohl(msg->content_length);
    if (msg->message_type != 'D')
        return PG_UNEXPECTED_LOG("Message of type '%c' received while waiting for row data ('D')", msg->message_type);
    if (length < 4 + 2 + 4 || length >= BUFFER_SIZE - 1)
        return PG_UNEXPECTED_LOG("Row data message has bad length %u", length);

    int16_t columns = ntohs(*(int16_t *) &msg->payload[0]);
    int32_t column_length = ntohl(*(int32_t *) &msg->payload[2]);
    if (columns != 1)
        return PG_UNEXPECTED_LOG("Unexpected number of columns %u", columns);
    else if (column_length < -1)
        return PG_UNEXPECTED_LOG("Column has unexpected length %d", column_length);
    else if (column_length == -1)
        return PG_NULL;
    else if (4 + 6 + (uint32_t) column_length != length)
        return PG_UNEXPECTED_LOG("Column length does not match message length");

    if (field.format == 0) {
        char *end = NULL;
        *value = strtol((const char *) &msg->payload[6], &end, 10);
        if (!end || *end || end != &msg->payload[6 + column_length])
            return PG_UNEXPECTED_LOG("Failed to parse number");
    } else if (field.format == 1) {
        if (column_length != 4)
            return PG_UNEXPECTED_LOG("Unexpected length %d for binary int4", column_length);
        *value = (int32_t) ntohl(*(uint32_t *) &msg->payload[6]);
    }
    return PG_SUCCESS;
}

#define PG_IMPL_QUERY_INT4(value_ptr, session, buffer, query) \
    ({ \
        enum pg_query_result _status; \
        if (PG_SEND_REVEALED(session, buffer, query) <= 0) { \
            pg_ossl_perror("failed to send query"); \
            _status = PG_NETWORK_ERROR; \
        } else { \
            _status = pg_read_int4(session, value_ptr); \
            if (_status != PG_NETWORK_ERROR) \
              _status = pg_wait_ready(session) ? PG_NETWORK_ERROR : _status; \
        } \
        _status; \
    })

#define PG_INT32_OR_NULL_TO_INT64(status, value) \
    ((status) == PG_NULL ? INT64_MIN : (uint64_t) (int64_t) (value))

static enum pg_query_result pg_read_inet(struct pg_session *session, struct in_addr __attribute__((may_alias)) *ip4,
                                         struct in6_addr __attribute__((may_alias)) *ip6, int *family) {
    char buffer[BUFFER_SIZE] = { 0 };
    struct pg_message *msg;
    struct pg_field_data field;
    enum pg_query_result result;

    if ((result = pg_read_row_desc(session, &field, 1)) != PG_SUCCESS)
        return result;

    if (field.table_oid != 0 || field.column_attrno != 0 || field.type_oid != 869 || field.type_size != -1 || field.type_modifier != -1)
        return PG_UNEXPECTED_LOG("Unexpected field description (expected inet)");

    msg = PG_RECEIVE(session, buffer);
    uint32_t length = ntohl(msg->content_length);
    if (msg->message_type != 'D')
        return PG_UNEXPECTED_LOG("Message of type '%c' received while waiting for row data ('D')", msg->message_type);
    if (length < 4 + 2 + 4 || length >= BUFFER_SIZE - 1)
        return PG_UNEXPECTED_LOG("Row data message has bad length %u", length);

    int16_t columns = ntohs(*(int16_t *) &msg->payload[0]);
    int32_t column_length = ntohl(*(int32_t *) &msg->payload[2]);
    if (columns != 1)
        return PG_UNEXPECTED_LOG("Unexpected number of columns %u", columns);
    else if (column_length < -1)
        return PG_UNEXPECTED_LOG("Column has unexpected length %d", column_length);
    else if (column_length == -1)
        return PG_NULL;
    else if (4 + 6 + (uint32_t) column_length != length)
        return PG_UNEXPECTED_LOG("Column length does not match message length");

    if (field.format == 0) {
        if (column_length >= INET6_ADDRSTRLEN)
            return PG_UNEXPECTED_LOG("Column is too long");
        char *printable = alloca(INET6_ADDRSTRLEN);
        memcpy(printable, &msg->payload[6], (size_t) column_length);
        printable[column_length] = 0;

        if (strchr(printable, ':'))
            *family = AF_INET6;
        else
            *family = AF_INET;

        if (inet_pton(*family, printable, *family == AF_INET ? (void *) ip4 : (void *) ip6) != 1)
            return PG_UNEXPECTED_LOG("Failed to parse inet value %s", printable);
    } else if (field.format == 1) {
        /* See src/include/utils/inet.h in the PostgreSQL code for the data layout here. */
        if (column_length < 4)
            return PG_UNEXPECTED_LOG("Column is too short for the inet header");

        int pg_family = msg->payload[6];
        int prefix_bits = (int) (unsigned char) msg->payload[7];
        int is_cidr = msg->payload[8] != '\0';
        int addr_length = (int) (unsigned char) msg->payload[9];
        if (column_length != 4 + addr_length)
            return PG_UNEXPECTED_LOG("Incorrect column length");

        if (is_cidr)
            return PG_UNEXPECTED_LOG("Received cidr, not inet");

        switch (pg_family) {
            case AF_INET:
                if (prefix_bits != 32 || addr_length != 4)
                    return PG_UNEXPECTED_LOG("Received non-/32 IPv4 address, or invalid length");
                _Static_assert(sizeof(*ip4) == 4, "Unexpected size for IPv4 addresses");
                memcpy(ip4, &msg->payload[10], sizeof(*ip4));
                *family = AF_INET;
                break;
            case AF_INET + 1: /* lol. Postgres doesn't use AF_INET6 here because that's not defined everywhere... */
                if (prefix_bits != 128 || addr_length != 16)
                    return PG_UNEXPECTED_LOG("Received non-/128 IPv6 address, or invalid length");
                _Static_assert(sizeof(*ip6) == 16, "Unexpected size for IPv6 addresses");
                memcpy(ip6, &msg->payload[10], sizeof(*ip6));
                *family = AF_INET6;
                break;
            default:
                return PG_UNEXPECTED_LOG("Unsupported address family %d", pg_family);
        }
    }
    return PG_SUCCESS;
}

#define PG_IMPL_QUERY_INET(ip4_ptr, ip6_ptr, family_ptr, session, buffer, query) \
    ({ \
        enum pg_query_result _status; \
        if (PG_SEND_REVEALED(session, buffer, query) <= 0) { \
            pg_ossl_perror("failed to send query"); \
            _status = PG_NETWORK_ERROR; \
        } else { \
            _status = pg_read_inet(session, ip4_ptr, ip6_ptr, family_ptr); \
            if (_status != PG_NETWORK_ERROR) \
              _status = pg_wait_ready(session) ? PG_NETWORK_ERROR : _status; \
        } \
        _status; \
    })

static _Thread_local uint32_t pg_function_oids[__QUERY_ALL_COUNT] = { 0 };

static enum pg_query_result pg_ensure_function_oids(struct pg_session *session) {
    char buffer[BUFFER_SIZE] = { 0 };
    struct pg_message *msg;
    struct pg_field_data fields[2];
    enum pg_query_result result;

    if (PG_SEND_REVEALED(session, buffer, OBF_GET_FUNCTION_OIDS) <= 0) {
        pg_ossl_perror("failed to send query");
        return PG_NETWORK_ERROR;
    }

    if ((result = pg_read_row_desc(session, fields, 2)) != PG_SUCCESS)
        return result;

    if (fields[0].type_oid != 26 || fields[0].type_size != 4 || fields[0].type_modifier != -1)
        return PG_UNEXPECTED_LOG("Unexpected field description for field 1 (expected oid)");
    if (fields[1].table_oid != 0 || fields[1].column_attrno != 0 || fields[1].type_oid != 23 || fields[1].type_size != 4 || fields[1].type_modifier != -1)
        return PG_UNEXPECTED_LOG("Unexpected field description for field 2 (expected int4)");

    for (;;) {
        msg = PG_RECEIVE(session, buffer);
        uint32_t length = ntohl(msg->content_length);
        if (msg->message_type == 'C')
            break;
        if (msg->message_type != 'D')
            return PG_UNEXPECTED_LOG("Message of type '%c' received while waiting for row data ('D')", msg->message_type);
        if (length < 4 + 2 + 4 * 2 || length >= BUFFER_SIZE - 2)
            return PG_UNEXPECTED_LOG("Row data message has bad length %u", length);

        int16_t columns = ntohs(*(int16_t *) &msg->payload[0]);
        if (columns != 2)
            return PG_UNEXPECTED_LOG("Expected 2 columns, received %hd", columns);

        int32_t oid_length = ntohl(*(uint32_t *) &msg->payload[2]);
        if (oid_length < 0 || 4 + 6 + (uint32_t) oid_length + 4 >= length)
            return PG_UNEXPECTED_LOG("OID length is negative or exceeds message");

        int32_t hash_length = ntohl(*(uint32_t *) &msg->payload[6 + oid_length]);
        if (hash_length < 0 || 4 + 6 + (uint32_t) oid_length + 4 + (uint32_t) hash_length != length)
            return PG_UNEXPECTED_LOG("Hash length is negative or exceeds message");

        int32_t values[2] = { 0 };
        int32_t lengths[2] = { oid_length, hash_length };

        _Static_assert(sizeof(values) / sizeof(values[0]) == sizeof(fields) / sizeof(fields[0]),
                       "Value count does not match field count");
        _Static_assert(sizeof(values) / sizeof(values[0]) == sizeof(lengths) / sizeof(lengths[0]),
                       "Value count does not match length count");

        char *position = &msg->payload[6];
        for (size_t i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
            if (fields[i].format == 0) {
                char *end = NULL;
                position[lengths[i]] = 0;
                values[i] = strtol(position, &end, 10);
                if (!end || *end || end != position + lengths[i])
                    return PG_UNEXPECTED_LOG("Failed to parse OID %s", position);
            } else if (fields[i].format == 1) {
                if (lengths[i] != sizeof(values[i]))
                    return PG_UNEXPECTED_LOG("Unexpected length for binary-format int4");
                values[i] = (int32_t) ntohl(*(uint32_t *) position);
            }
            position += lengths[i] + 4;
        }

        switch (values[1]) {
            /* Switch on hashtext(proname) */
            case -105682525: pg_function_oids[QUERY_DB_ACTIVE_USERS] = values[0]; break;
            case -1226815886: pg_function_oids[QUERY_DB_FREE_IP_RANGES] = values[0]; break;
            case 293437665: pg_function_oids[QUERY_DB_USER_DROPPED_PACKETS] = values[0]; break;
            case 233454956: pg_function_oids[QUERY_DB_USER_DROPPED_BYTES] = values[0]; break;
            default: break;
        }
    }
    return PG_SUCCESS;
}

#define PG_IMPL_GET_OIDS(session) \
    ({ \
        enum pg_query_result _status = pg_ensure_function_oids(session); \
        if (_status != PG_NETWORK_ERROR) \
            _status = pg_wait_ready(session) ? PG_NETWORK_ERROR : _status; \
        _status; \
    })

static enum pg_query_result pg_invoke_function_int4(int32_t *value, struct pg_session *session, uint32_t oid, uint64_t *argument) {
    char buffer[BUFFER_SIZE] = { 0 };
    unsigned query_size;
    struct pg_message *msg;

    buffer[0] = 'F';
    /*
     *    length  oid      #fmt      #arg len(arg) arg              outfmt
     * 46 ....... ........ 0001 0001 0001 00000008 8899aabbccddeeff 0001
     *
     *    length  oid      #fmt #arg outfmt
     * 46 ....... ........ 0000 0000 0001
     */
    if (argument) {
        memcpy(
            &buffer[9],
            /* Format specifiers */ "\x00\x01" "\x00\x01"
            /* Arguments */ "\x00\x01" "\x00\x00\x00\x08" /* + 8 bytes */,
            10
        );
        *(uint32_t *) &buffer[19] = htonl(*argument >> 32);
        *(uint32_t *) &buffer[23] = htonl(*argument & 0xffffffff);
    }
    query_size = argument ? 29 : 15;
    buffer[4] = query_size - 1;
    *(uint32_t *) &buffer[5] = htonl(oid);
    *(uint16_t *) &buffer[query_size - 2] = htons(1); /* Please give me a binary response */

    if (SSL_write(session->ssl, buffer, query_size) <= 0) {
        pg_ossl_perror("failed to send query");
        return PG_NETWORK_ERROR;
    }

    msg = PG_RECEIVE(session, buffer);
    uint32_t length = ntohl(msg->content_length);
    if (msg->message_type != 'V' || length != 12)
        return PG_UNEXPECTED_LOG("Unexpected response (type '%c'), expected 'V' of length 12", msg->message_type);

    uint32_t result_length = ntohl(*(uint32_t *) &msg->payload[0]);
    if (result_length != 4)
        return PG_UNEXPECTED_LOG("Unexpected data length for value of type int4");

    *value = ntohl(*(uint32_t *) &msg->payload[4]);
    return PG_SUCCESS;
}

#define PG_IMPL_FUNCTION_INT4(value_ptr, session, oid, argument) \
    ({ \
        enum pg_query_result _status = pg_invoke_function_int4(value_ptr, session, oid, argument); \
        if (_status != PG_NETWORK_ERROR) \
            _status = pg_wait_ready(session) ? PG_NETWORK_ERROR : _status; \
        _status; \
    })

static int pg_handle_work(struct pg_session *session, struct pg_work_item *item) {
    // Handles a work item. Returns a non-null value _only_ if the actual connection failed.
    // Postgres errors are fine, and just trigger an error response.
    // Invalid query identifiers are just dropped, this should have been checked earlier.

    char buffer[OBF_MAX_LEN];
    enum pg_query_result status;
    enum {
        INT4,
        IPV4,
        IPV6,
    } output_type;
    union {
        int32_t int4;
        struct in_addr ip4;
        struct in6_addr ip6;
        struct sockaddr_storage sockaddr;
    } value;
    int family = 0;
    socklen_t length = sizeof(value.sockaddr);

    switch (item->query_identifier) {
        case QUERY_SOCKET_SERVER_ADDR:
            if (getpeername(session->tcp_socket, (struct sockaddr *) &value.sockaddr, &length) < 0)
                return -1;
            if (value.sockaddr.ss_family == AF_INET) {
                storage->monitoring[MON_DB_SOCKET_PORT] = ntohs(((struct sockaddr_in *) &value.sockaddr)->sin_port);
                storage->monitoring[MON_DB_SOCKET_IPV4] = ((struct sockaddr_in *) &value.sockaddr)->sin_addr.s_addr;
                memmove(&value.ip4, &((struct sockaddr_in *) &value.sockaddr)->sin_addr, sizeof(value.ip4));
                output_type = IPV4;
                status = PG_SUCCESS;
            } else if (value.sockaddr.ss_family == AF_INET6) {
                uint64_t *parts = (uint64_t *) ((struct sockaddr_in6 *) &value.sockaddr)->sin6_addr.s6_addr;
                storage->monitoring[MON_DB_SOCKET_PORT] = ntohs(((struct sockaddr_in6 *) &value.sockaddr)->sin6_port);
                storage->monitoring[MON_DB_SOCKET_IPV6_HIGH] = parts[0];
                storage->monitoring[MON_DB_SOCKET_IPV6_LOW] = parts[1];
                memmove(&value.ip6, &((struct sockaddr_in6 *) &value.sockaddr)->sin6_addr, sizeof(value.ip6));
                output_type = IPV6;
                status = PG_SUCCESS;
            } else {
                status = PG_UNEXPECTED;
            }
            if (status == PG_SUCCESS)
                status = PG_IMPL_GET_OIDS(session);
            break;
        case QUERY_SOCKET_CLIENT_ADDR:
            if (getsockname(session->tcp_socket, (struct sockaddr *) &value.sockaddr, &length) < 0)
                return -1;
            if (value.sockaddr.ss_family == AF_INET) {
                storage->monitoring[MON_SNMP_SOCKET_IPV4] = ((struct sockaddr_in *) &value.sockaddr)->sin_addr.s_addr;
                memmove(&value.ip4, &((struct sockaddr_in *) &value.sockaddr)->sin_addr, sizeof(value.ip4));
                output_type = IPV4;
                status = PG_SUCCESS;
            } else if (value.sockaddr.ss_family == AF_INET6) {
                uint64_t *parts = (uint64_t *) ((struct sockaddr_in6 *) &value.sockaddr)->sin6_addr.s6_addr;
                storage->monitoring[MON_SNMP_SOCKET_IPV6_HIGH] = parts[0];
                storage->monitoring[MON_SNMP_SOCKET_IPV6_LOW] = parts[1];
                memmove(&value.ip6, &((struct sockaddr_in6 *) &value.sockaddr)->sin6_addr, sizeof(value.ip6));
                output_type = IPV6;
                status = PG_SUCCESS;
            } else {
                status = PG_UNEXPECTED;
            }
            if (status == PG_SUCCESS)
                status = PG_IMPL_GET_OIDS(session);
            break;
        case QUERY_DB_SERVER_ADDR:
            status = PG_IMPL_QUERY_INET(&value.ip4, &value.ip6, &family, session, buffer, OBF_QUERY_DB_SERVER_ADDR);
            if (status == PG_SUCCESS) {
                switch (family) {
                    case AF_INET:
                        storage->monitoring[MON_DB_IPV4] = value.ip4.s_addr;
                        output_type = IPV4;
                        break;
                    case AF_INET6:
                        storage->monitoring[MON_DB_IPV6_HIGH] = ((uint64_t *) value.ip6.s6_addr)[0];
                        storage->monitoring[MON_DB_IPV6_LOW] = ((uint64_t *) value.ip6.s6_addr)[1];
                        output_type = IPV6;
                        break;
                    default:
                        status = PG_UNEXPECTED;
                }
            }
            break;
        case QUERY_DB_CLIENT_ADDR:
            status = PG_IMPL_QUERY_INET(&value.ip4, &value.ip6, &family, session, buffer, OBF_QUERY_DB_CLIENT_ADDR);
            if (status == PG_SUCCESS) {
                switch (family) {
                    case AF_INET:
                        storage->monitoring[MON_SNMP_IPV4] = value.ip4.s_addr;
                        output_type = IPV4;
                        break;
                    case AF_INET6:
                        storage->monitoring[MON_SNMP_IPV6_HIGH] = ((uint64_t *) value.ip6.s6_addr)[0];
                        storage->monitoring[MON_SNMP_IPV6_LOW] = ((uint64_t *) value.ip6.s6_addr)[1];
                        output_type = IPV6;
                        break;
                    default:
                        status = PG_UNEXPECTED;
                }
            }
            break;
        case QUERY_DB_NAME_HASH:
            status = PG_IMPL_QUERY_INT4(&value.int4, session, buffer, OBF_QUERY_DB_SESSION_USER_HASH);
            output_type = INT4;
            if (PG_IS_OK(status))
                storage->monitoring[MON_DB_NAME_HASH] = PG_INT32_OR_NULL_TO_INT64(status, value.int4);
            break;
        case QUERY_DB_SESSION_USER_HASH:
            status = PG_IMPL_QUERY_INT4(&value.int4, session, buffer, OBF_QUERY_DB_SESSION_USER_HASH);
            output_type = INT4;
            if (PG_IS_OK(status))
                storage->monitoring[MON_DB_USER_HASH] = PG_INT32_OR_NULL_TO_INT64(status, value.int4);
            break;
        case QUERY_DB_SYSTEM_USER_HASH:
            status = PG_IMPL_QUERY_INT4(&value.int4, session, buffer, OBF_QUERY_DB_SYSTEM_USER_HASH);
            output_type = INT4;
            if (PG_IS_OK(status))
                storage->monitoring[MON_DB_SYSUSER_HASH] = PG_INT32_OR_NULL_TO_INT64(status, value.int4);
            break;
        case QUERY_DB_ACTIVE_USERS:
            status = PG_IMPL_FUNCTION_INT4(&value.int4, session, pg_function_oids[item->query_identifier], NULL);
            output_type = INT4;
            if (PG_IS_OK(status))
                storage->monitoring[MON_STATS_USERS] = PG_INT32_OR_NULL_TO_INT64(status, value.int4);
            break;
        case QUERY_DB_FREE_IP_RANGES:
            status = PG_IMPL_FUNCTION_INT4(&value.int4, session, pg_function_oids[item->query_identifier], NULL);
            output_type = INT4;
            if (PG_IS_OK(status))
                storage->monitoring[MON_STATS_FREE_IP_RANGES] = PG_INT32_OR_NULL_TO_INT64(status, value.int4);
            break;
        case QUERY_DB_USER_DROPPED_PACKETS:
        case QUERY_DB_USER_DROPPED_BYTES:
            status = PG_IMPL_FUNCTION_INT4(&value.int4, session, pg_function_oids[item->query_identifier], &item->user_identifier);
            output_type = INT4;
            break;
        default:
            status = PG_NULL;
    }

    if (item->socket > 0 && item->pdu != NULL) {
        switch (status) {
            case PG_NETWORK_ERROR:
            case PG_DB_ERROR:
            case PG_UNEXPECTED:
                // Send error response
                snmp_free_varbind(item->pdu->variables);
                item->pdu->variables = NULL;
                item->pdu->errstat = (status == PG_NETWORK_ERROR) ? SNMP_ERR_RESOURCEUNAVAILABLE : SNMP_ERR_GENERR;
                break;
            case PG_NULL:
                if (!item->pdu->variables)
                    break;
                snmp_free_varbind(item->pdu->variables->next_variable);
                snmp_set_var_typed_value(item->pdu->variables, ASN_NULL, NULL, 0);
                break;
            case PG_SUCCESS:
                // Send appropriate value response
                if (!item->pdu->variables)
                    break;
                snmp_free_varbind(item->pdu->variables->next_variable);
                switch (output_type) {
                    case INT4: snmp_set_var_typed_value(item->pdu->variables, ASN_INTEGER, &value.int4, sizeof(value.int4)); break;
                    case IPV4: snmp_set_var_typed_value(item->pdu->variables, ASN_OCTET_STR, &value.ip4, sizeof(value.ip4)); break;
                    case IPV6: snmp_set_var_typed_value(item->pdu->variables, ASN_OCTET_STR, &value.ip6, sizeof(value.ip6)); break;
                }
                break;
        }
        send_response(item->socket, &item->client, sizeof(item->client), item->pdu);
        snmp_free_pdu(item->pdu);
    }

    return PG_IS_OK(status) ? 0 : -1;
}

const int PG_WORKER_TIMEOUT = 5;

static void *pg_worker(void *arg) {
    int result;
    struct pg_session session = { 0 };
    struct pg_work_queue *queue = arg;
    struct pg_work_item item;

    while (!queue->shutdown) {
        if (pg_random() & 1)
            result = pg_tls_connect(&session, (const struct sockaddr *) &SERVER_IPV4, sizeof(SERVER_IPV4));
        else
            result = pg_tls_connect(&session, (const struct sockaddr *) &SERVER_IPV6, sizeof(SERVER_IPV6));

        if (result) {
            fprintf(stderr, "failed to connect to database\n");
            goto retry;
        }

        if (pg_connect(&session)) {
            fprintf(stderr, "failed to connect to database\n");
            goto pgsql_retry;
        }

        if (PG_IMPL_GET_OIDS(&session) != PG_SUCCESS) {
            fprintf(stderr, "database connection failed\n");
            goto retry;
        }

        while (!pg_work_queue_get(queue, &item, PG_WORKER_TIMEOUT)) {
            if (pg_handle_work(&session, &item)) {
                fprintf(stderr, "database connection failed\n");
                goto retry;
            }
        }

        pg_disconnect(&session);
        pg_tls_disconnect(&session);
        break;

pgsql_retry:
        pg_tls_disconnect(&session);

retry:
        sleep(PG_WORKER_TIMEOUT);
        continue;
    }

    return NULL;
}

int pg_spawn_worker(pthread_t *thread, struct pg_work_queue *queue) {
    return pthread_create(thread, NULL, pg_worker, queue);
}
