#include <stdio.h>
//#define DEBUG 1

#if DEBUG
#define DBG_PRINTF(...) fprintf(stderr, "DEBUG: " __VA_ARGS__)
void debug_print_client_addr(struct sockaddr_in *clientaddr);
#else
#define DBG_PRINTF( ...)
#define debug_print_client_addr(x) do { } while (0)
#endif

