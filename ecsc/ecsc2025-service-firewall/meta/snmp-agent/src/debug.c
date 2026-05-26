#include <netdb.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include "debug.h"

#if DEBUG
void debug_print_client_addr(struct sockaddr_in *clientaddr) {
    struct hostent *hostp;
    char *hostaddr;
    hostp = gethostbyaddr(&clientaddr->sin_addr.s_addr, sizeof(clientaddr->sin_addr.s_addr), AF_INET);
    if (hostp == NULL) {
        DBG_PRINTF("failed to gethostbyaddr\n");
        return;
    }
    hostaddr = inet_ntoa(clientaddr->sin_addr);
    if (hostaddr == NULL) {
        DBG_PRINTF("failed to inet_ntoa\n");
    }
    DBG_PRINTF("%s", hostaddr);
}
#endif
