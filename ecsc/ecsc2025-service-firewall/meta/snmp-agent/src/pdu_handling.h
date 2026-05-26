#include "general.h"

void handle_packet(int sock, struct sockaddr_in6 *clientaddr, socklen_t clientlen, uint8_t *buf, ssize_t len);
void send_response(int sock, struct sockaddr_in6 *clientaddr, socklen_t clientlen, netsnmp_pdu *pdu);
