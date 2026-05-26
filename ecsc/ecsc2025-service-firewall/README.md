Firewall
========

Authors:
* Diff-fusion (Felix Buchmann)
* hlt (Tobias Holl)

Categories:
* misc
* pwn
* rev

Description
-----------

> As part of our ongoing commitment to maintaining a secure and resilient technology environment, the Electric Catfish Systems IT department has successfully completed its comprehensive 2025 review of our network security infrastructure. This initiative involved the replacement of our existing network edge with a new state-of-the-art security appliance engineered by Guppy Networks.
>
> This new firewall device incorporates advanced threat detection and response capabilities, improved remote access management, and greater scalability to support the evolving needs of our business. The transition was executed with minimal disruption and positions us to better safeguard company data and user connectivity in an increasingly complex cybersecurity landscape.
>
> We appreciate your continued support as we invest in strengthening our digital foundation.

Overview
--------

This service is an enterprise firewall, with some additional sub-services behind it (which interact with the firewall).

Users can communicate with those services through a VPN endpoint on the firewall.
Additionally, there is a publicly accessibly web interface for self-registration.

We'll use some `nftables` language throughout, but the service does not actually use `nftables` under the hood (since kernel-level filtering makes everything more annoying to host).

![Structure of the service](/../assets/architecture.svg)

The firewall stores a log of filtered traffic (i.e., invalid/dropped packets) in the database.
Via the web interface, it is possible to view the traffic dropped for the current user's VPN connection (i.e., only your own traffic), but connecting directly to the database server's port is prohibited by the firewall rules.

The FTP server is mostly boilerplate written in Python, with the actual implementation provided by [`pyftpdlib`](https://github.com/giampaolo/pyftpdlib).
Only the integration with the database, file system quotas (for safety/availability reasons), and the dynamic creation of per-user home directories is custom code.

On the firewall host, a binary-only SNMP agent provides firewall statistics and some configuration data. Within the firewall's web frontend, we offer an SNMP manager that visualizes some of these statistics, and expose an "expert" mode that allows making raw SNMP GET and SET requests to the agent (but not SNMP walks / bulk requests).


### Flag Store 1

The checker stores flags as invalid or dropped packets (of its own user) in the firewall log.

The checker's user name is provided as attack info.

### Flag Store 2

Flags are stored in the SNMP agent via the SNMP manager web interface.

Each user is assigned a random identifier (which is provided as attack info), and the flags are stored at an OID derived from that identifier and a secret 64-bit key.


Vulnerabilities
---------------

### Flag Store 1, Vuln 1

This is a common firewall bug: in order to not filter the FTP and SNMP server's responses to clients, you usually need to filter on destination port and connection state. Despite the fact that most firewalls support `conntrack`, it is still remarkably common (and the bug here) to instead also allowlist the server's response via their source port --- so if you set the source port of your traffic to one of the allowed ports (for the FTP server or the SNMP manager's frontend), you can directly send queries to the database server in its binary protocol, and read out the flags.

* Difficulty: easy
* Discoverability: easy
* Patchability: easy

### Flag Store 1, Vuln 2

FTP passive mode requests that the client connects to the server on a separate data port to transfer data. The firewall needs to account for this. In a typical passive-mode connection, the client sends a `PASV` request to the server, which responds with `227 Entering Passive Mode (192,0,2,42,4,210)` to request a connection to its IP (192.0.2.42) and port (`4 * 256 + 210`, i.e., 1234). Unfortunately, the pattern matching for this case is broken in the firewall — any response from the FTP server that matches a (rather verbose) regular expression leads to the firewall allowing passive mode traffic to the specified host and port. Since we can embed content in the FTP server's responses (e.g. by uploading a file with a specially crafted filename), we can convince the firewall to allow traffic to host/port combinations that would not ordinarily be allowed.

* Difficulty: easy
* Discoverability: medium
* Patchability: medium

### Flag Store 1, Vuln 3

Some FTP servers (e.g., FileZilla, unFTP, Apache FtpServer, ...) do not check the target address of active-mode data connections (`PORT`, etc.) against where the client actually this. This is by design (for FXP, which we don't have), but can also be used to attack other servers (the "bounce attack", RFC 2577 §2). By uploading a malicious file to the FTP server, then "retrieving" it via active mode, we can trick the FTP server into sending raw commands to the database server. This requires manually crafting the database commands.

* Difficulty: medium
* Discoverability: medium
* Patchability: medium

### Flag Store 2, Vuln 1

Bad filtering (no reverse path filtering, and martian packets are routed) means that the SNMP agent is directly reachable by addressing VPN traffic to `127.0.0.1`. This requires crafting packets by hand, since the default VPN client will not usually produce such traffic. Then, it is possible to use GETNEXT ~or GETBULK~ queries on the agent to walk the tree of SNMP values and leak the flags.

* Difficulty: medium
* Discoverability: medium
* Patchability: easy

### Flag Store 2, Vuln 2

The monitoring OID tree in the SNMP agent is implemented as simple arrays on the heap. Sending bad OID nodes allows reading out-of-bounds on these arrays and leaking the flags stored in the SNMP agent's memory.

* Difficulty: medium
* Discoverability: hard
* Patchability: hard

### Flag Store 2, Vuln 3

The manager allows sending raw messages to the SNMP agent. But a check is performed to only allow GET requests to prevent leaking the flags via GETNEXT. The parsing logic for length fields in the message is incorrect, which allows bypassing the check on the message type. Then, the flags can once again be leaked using GETNEXT messages.

* Difficulty: medium
* Discoverability: medium
* Patchability: easy


Patches
-------

### Flag Store 1, Vuln 1

Simply replace the `tcp sport` default rule with one that allows established / related connections only.

### Flag Store 1, Vuln 2

Enforce that passive-mode connections are only allowed to the server that issued the `Entering Passive Mode` response.

### Flag Store 1, Vuln 3

Enable active-mode IP checking in the FTP server configuration.

### Flag Store 2, Vuln 1

Apply filtering at the VPN endpoint to only allow traffic to actual VPN hosts, never to the firewall's local IP addresses.

### Flag Store 2, Vuln 2

Binary-patch the SNMP agent to check the indices properly, or implement filtering in the manager (but see flag store 2, vuln 3).

### Flag Store 2, Vuln 3

Fix the parsing logic in the manager.

State
-----

The service stores its state in multiple Docker volumes (as shown below), which are mounted into the containers accordingly. We use the `subpath` key to make mounts partially read-only as appropriate.

The `init` container sets up missing shared state as needed.

```
├── firewall-db
│   ├── data                PostgreSQL storage root directory
│   ├── secrets
│   │   ├── admin           Admin password for the database (randomly generated)
│   │   ├── authentication  Password for the authentication user (randomly generated)
│   │   ├── ftp             Password for the FTP server's DB user (randomly generated)
│   │   └── stats           Password for a low-privileged stats user (randomly generated)
│   └── tls
│       ├── tls.crt         TLS certificate (signed by the internal CA)
│       └── tls.key         Key for the TLS certificate
├── firewall-firewall
│   ├── secrets
│   │   └── db              Password for the authentication user (see above)
│   └── tls
│       └── ca.crt          Internal CA certificate
├── firewall-ftp
│   ├── data                FTP storage root directory
│   ├── secrets
│   │   └── db              Password for the ftp DB user (see above)
│   └── tls
│       ├── ca.crt          Internal CA certificate
│       ├── tls.crt         TLS certificate for the FTP server
│       └── tls.key         Private key for the FTP server's TLS certificate
├── firewall-internal
│   └── ca
│       ├── ca.crt          Internal (self-signed) CA certificate
│       └── ca.key          CA signing key
└── firewall-snmp
    ├── data
    │   └── agent           Persistent storage for the SNMP agent
    └── secrets
        └── auth_community  Community string for write operations (randomly generated)
```
