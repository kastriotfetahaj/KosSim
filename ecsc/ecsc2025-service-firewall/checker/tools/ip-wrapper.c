#define _GNU_SOURCE
#include <err.h>
#include <net/if.h>
#include <regex.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define BASE_IP "/bin/ip"
#define IFACE_PREFIX "vpn"

int is_fwmark(char *arg)
{
    char *end = NULL;
    if (!arg) return 0;
    unsigned long fwmark = strtoul(arg, &end, 0);
    return (end && *end == '\0' && 0 < fwmark && fwmark <= UINT32_MAX);
}

int is_table(char *arg)
{
    char *end = NULL;
    if (!arg) return 0;
    unsigned long fwmark = strtoul(arg, &end, 0);
    return (end && *end == '\0' && 0 < fwmark && fwmark <= 32765);
}

int is_interface(char *arg)
{
    if (!arg || strnlen(arg, IFNAMSIZ) >= IFNAMSIZ) return 0;
    return !strncmp(arg, IFACE_PREFIX, strlen(IFACE_PREFIX));
}

int is_mtu(char *arg)
{
    char *end = NULL;
    if (!arg) return 0;
    unsigned long mtu = strtoul(arg, &end, 0);
    return (end && *end == '\0' && 1280 <= mtu && mtu <= 2048);
}

int is_ip(char *arg)
{
    char buf[128];
    regex_t re;
    int result;

    if (!arg)
        return 0;

    result = regcomp(&re, "^[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}$", REG_EXTENDED | REG_NOSUB);
    if (result) {
        regerror(result, &re, buf, sizeof(buf));
        errx(EXIT_FAILURE, "failed to compile regex: %s", buf);
    }

    if (regexec(&re, arg, 0, NULL, 0) != REG_NOMATCH)
        return 1; // ~roughly an IPv4 address

    result = regcomp(&re, "^[0-9a-f:]+$", REG_EXTENDED | REG_NOSUB);
    if (result) {
        regerror(result, &re, buf, sizeof(buf));
        errx(EXIT_FAILURE, "failed to compile regex: %s", buf);
    }

    if (regexec(&re, arg, 0, NULL, 0) != REG_NOMATCH)
        return 1; // ~roughly an IPv6 address

    return 0;
}

int is_network(char *arg)
{
    char *slash = strchr(arg, '/');
    if (!slash) return 0;
    *slash = '\0';
    int front = is_ip(arg);
    *slash = '/';
    if (!front) return 0;
    char *end = NULL;
    unsigned long prefixlen = strtoul(slash + 1, &end, 10);
    return (end && *end == '\0' && prefixlen <= 128);
}

void check_ip_rule(char **args)
{
    if (strcmp(args[0], "rule"))
        errx(EXIT_FAILURE, "ip rule: expected 'ip _rule_'");
    if (strcmp(args[1], "add") && strcmp(args[1], "del"))
        errx(EXIT_FAILURE, "ip rule: expected 'ip rule _{add,del}_'");
    if (strcmp(args[2], "from"))
        errx(EXIT_FAILURE, "ip rule: expected 'ip rule %s _from_'", args[1]);
    if (strcmp(args[3], "all"))
        errx(EXIT_FAILURE, "ip rule: expected 'ip rule %s from _all_'", args[1]);
    if (strcmp(args[4], "fwmark"))
        errx(EXIT_FAILURE, "ip rule: expected 'ip rule %s from all _fwmark_'", args[1]);
    if (!is_fwmark(args[5]))
        errx(EXIT_FAILURE, "ip rule: expected 'ip rule %s from all fwmark _<fwmark>_'", args[1]);
    if (strcmp(args[6], "lookup"))
        errx(EXIT_FAILURE, "ip rule: expected 'ip rule %s from all fwmark %s _table_'", args[1], args[5]);
    if (!is_table(args[7]))
        errx(EXIT_FAILURE, "ip rule: expected 'ip rule %s from all fwmark %s table _<table>_'", args[1], args[5]);
    if (args[8])
        errx(EXIT_FAILURE, "ip rule: extraneous arguments");
}

void check_ip_link(char **args)
{
    if (strcmp(args[0], "link"))
        errx(EXIT_FAILURE, "ip link: expected 'ip _link_'");
    if (strcmp(args[1], "set"))
        errx(EXIT_FAILURE, "ip link: expected 'ip link _set_'");
    if (strcmp(args[2], "dev"))
        errx(EXIT_FAILURE, "ip link: expected 'ip link set _dev_'");
    if (!is_interface(args[3]))
        errx(EXIT_FAILURE, "ip link: expected 'ip link set dev _<interface>_'");

    if (!strcmp(args[4], "up") || !strcmp(args[4], "down")) {
        if (args[5])
            errx(EXIT_FAILURE, "ip link: extraneous arguments");
    } else if (!strcmp(args[4], "mtu")) {
        if (!is_mtu(args[5]))
            errx(EXIT_FAILURE, "ip link: expected 'ip link set dev %s mtu _<mtu>_", args[3]);
        if (args[6])
            errx(EXIT_FAILURE, "ip link: extraneous arguments");
    } else {
        errx(EXIT_FAILURE, "ip link: expected 'ip link set dev %s _mtu/up/down_'", args[3]);
    }
}

void check_ip_route(char **args)
{
    if (strcmp(args[0], "route"))
        errx(EXIT_FAILURE, "ip route: expected 'ip _route_'");
    if (!strcmp(args[1], "add")) {
        if (!is_network(args[2]))
            errx(EXIT_FAILURE, "ip route: expected 'ip route add _<ip>/<prefixlen>_'");
        if (strcmp(args[3], "dev"))
            errx(EXIT_FAILURE, "ip route: expected 'ip route add %s _dev_'", args[2]);
        if (!is_interface(args[4]))
            errx(EXIT_FAILURE, "ip route: expected 'ip route add %s dev _<interface>_'", args[2]);
        if (strcmp(args[5], "scope"))
            errx(EXIT_FAILURE, "ip route: expected 'ip route add %s dev %s _scope_'", args[2], args[4]);
        if (strcmp(args[6], "link"))
            errx(EXIT_FAILURE, "ip route: expected 'ip route add %s dev %s scope _link_'", args[2], args[4]);
        if (strcmp(args[7], "src"))
            errx(EXIT_FAILURE, "ip route: expected 'ip route add %s dev %s scope link _src_'", args[2], args[4]);
        if (!is_ip(args[8]))
            errx(EXIT_FAILURE, "ip route: expected 'ip route add %s dev %s scope link src _<ip>_'", args[2], args[4]);
        if (strcmp(args[9], "table"))
            errx(EXIT_FAILURE, "ip route: expected 'ip route add %s dev %s scope link src %s _table_'", args[2], args[4], args[8]);
        if (!is_table(args[10]))
            errx(EXIT_FAILURE, "ip route: expected 'ip route add %s dev %s scope link src %s table _<table>_'", args[2], args[4], args[8]);
        if (args[11])
            errx(EXIT_FAILURE, "ip route: extraneous arguments");
    } else if (!strcmp(args[1], "flush")) {
        if (strcmp(args[2], "table"))
            errx(EXIT_FAILURE, "ip route: expected 'ip route flush _table_'");
        if (!is_table(args[3]))
            errx(EXIT_FAILURE, "ip route: expected 'ip route flush table _<table>_'");
        if (args[4])
            errx(EXIT_FAILURE, "ip route: extraneous arguments");
    } else if (!strcmp(args[1], "show")) {
        if (strcmp(args[2], "table"))
            errx(EXIT_FAILURE, "ip route: expected 'ip route show _table_'");
        if (strcmp(args[3], "local"))
            errx(EXIT_FAILURE, "ip route: expected 'ip route show table _local_'");
        if (strcmp(args[4], "dev"))
            errx(EXIT_FAILURE, "ip route: expected 'ip route show table local _dev_'");
        if (!is_interface(args[5]))
            errx(EXIT_FAILURE, "ip route: expected 'ip route show table local dev _<interface>_'");
        if (args[6])
            errx(EXIT_FAILURE, "ip route: extraneous arguments");
    } else {
        errx(EXIT_FAILURE, "ip route: expected 'ip route _add/flush/show_'");
    }
}

void check_ip_addr(char **args)
{
    if (strcmp(args[0], "addr"))
        errx(EXIT_FAILURE, "ip addr: expected 'ip _addr_'");
    if (!strcmp(args[1], "add")) {
        if (!is_network(args[2]))
            errx(EXIT_FAILURE, "ip addr: expected 'ip addr add _<ip>/<prefixlen>_'");
        if (strcmp(args[3], "dev"))
            errx(EXIT_FAILURE, "ip addr: expected 'ip addr add %s _dev_'", args[2]);
        if (!is_interface(args[4]))
            errx(EXIT_FAILURE, "ip addr: expected 'ip addr add %s dev _<interface>_'", args[2]);
        if (strcmp(args[5], "noprefixroute"))
            errx(EXIT_FAILURE, "ip addr: expected 'ip addr add %s dev %s _noprefixroute_'", args[2], args[4]);
        if (args[6] && strcmp(args[6], "nodad"))
            errx(EXIT_FAILURE, "ip addr: expected 'ip addr add %s dev %s noprefixroute _nodad_'", args[2], args[4]);
        if (args[6] && args[7])
            errx(EXIT_FAILURE, "ip addr: extraneous arguments");
    } else if (!strcmp(args[1], "flush")) {
        if (strcmp(args[2], "dev"))
            errx(EXIT_FAILURE, "ip addr: expected 'ip addr flush _dev_'");
        if (!is_interface(args[3]))
            errx(EXIT_FAILURE, "ip addr: expected 'ip addr flush dev _<interface>_'");
        if (args[4])
            errx(EXIT_FAILURE, "ip addr: extraneous arguments");
    } else {
        errx(EXIT_FAILURE, "ip addr: expected 'ip addr _add/flush_'");
    }
}

int main(int argc, char *argv[], char *envp[])
{
    // Commands executed by the VPN implementation in the checker (in checker mode):
    //   -<version> route add <ip>/<prefixlen> dev <interface> scope link src <ip> table <table>
    //   -<version> route flush table <table>
    //   -<version> route show table local dev <interface>
    //   -<version> addr add <ip>/<prefixlen> dev <interface> noprefixroute [nodad]
    //   -<version> addr flush dev <interface>
    //   link set dev <interface> mtu <mtu>
    //   link set dev <interface> up/down
    //   rule add from all fwmark <fwmark> lookup <table>
    //   rule del from all fwmark <fwmark> lookup <table>
    // where <fwmark> is always an integer, <table> is always 1337, and <interface> starts with vpn.

    if (setresuid(0, 0, 0))
        err(EXIT_FAILURE, "failed to elevate privileges");

    (void) argc;
    char **arg = &argv[1];

    // First, check for -j and -<version>.
    char *version = NULL;
    for (;;) {
        if (!strcmp(*arg, "-j")) {
            ++arg;
        } else if (!strcmp(*arg, "-4") || !strcmp(*arg, "-6")) {
            version = *arg;
            ++arg;
        } else {
            break;
        }
    }

    // Now, switch on the command.
    if (!strcmp(*arg, "route")) {
        if (!version)
            errx(EXIT_FAILURE, "ip route only allowed with -<version>");
        check_ip_route(arg);
    } else if (!strcmp(*arg, "addr")) {
        if (!version)
            errx(EXIT_FAILURE, "ip addr only allowed with -<version>");
        check_ip_addr(arg);
    } else if (!strcmp(*arg, "link")) {
        if (version)
            errx(EXIT_FAILURE, "ip link not allowed with -<version>");
        check_ip_link(arg);
    } else if (!strcmp(*arg, "rule")) {
        if (!version)
            errx(EXIT_FAILURE, "ip rule only allowed with -<version>");
        check_ip_rule(arg);
    } else {
        errx(EXIT_FAILURE, "unknown or disallowed command: ip %s", *arg);
    }

    if (execve(BASE_IP, argv, envp))
        err(EXIT_FAILURE, "failed to execute %s", BASE_IP);
}
