# Reference NFT

```shell
add rule ctfr-gates gates ip daddr @g-gameservers meta l4proto icmp accept comment "bypass gates for gameserver";
add rule ctfr-gates gates ip daddr @g-gameservers tcp dport { 1337 } accept comment "bypass gates for submitter";
add rule ctfr-gates gates ip saddr @t-orga accept comment "bypass gates for team orga";

add chain ctfr-gates static-forward;
delete chain ctfr-gates static-forward;
add chain ctfr-gates static-forward {
  type filter hook forward priority 1; policy drop;

  tcp dport 2113 accept comment "Allow canary";
  tcp sport 2113 ct direction reply accept comment "reply canary";

  ip saddr @t-orga accept;
  ip daddr @t-orga ct direction reply accept;

  ip saddr @g-gameservers accept;
  ip daddr @g-gameservers ct direction reply accept;
  ip saddr @g-checkers accept;
  ip daddr @g-checkers ct direction reply accept;
  ip saddr 10.233.0.0/16 accept comment "Allow overlay peers";
  ip daddr 10.233.0.0/16 ct direction reply accept comment "Allow overlay peers";
        
  ip daddr @g-gameservers meta l4proto icmp accept comment "Allow gameserver icmp";
  ip daddr @g-gameservers tcp dport { 80, 1337, 8080 } accept comment "Allow scoreboard and submitter";

  iifname team-cloud ip daddr != 10.0.0.0/8  counter accept comment "Vulnbox internet";
  oifname team-cloud ct direction reply counter accept comment "Vulnbox internet";
  iifname team-cloud ct direction reply counter accept comment "Replies from team-cloud to orga";

  ip saddr . ip daddr @same-team accept comment "Team internal traffic";
  iifname tt-* oifname team-cloud accept comment "Local team -> Local team cloud";
  ip saddr @any-team meta l4proto != {tcp, icmp} counter drop comment "Only icmp and tcp to other teams";

  ip saddr . ip daddr != @same-team ip daddr @any-vulnbox tcp dport 8000-8999 drop comment "Protected port range";
  ip saddr . ip daddr != @same-team ip daddr @any-vulnbox accept comment "Accept other traffic only to to vulnboxes";
  ip saddr @any-vulnbox ct direction reply accept comment "Reply from vulnbox";
  counter;
}  
add chain ctfr-gates nat;
delete chain ctfr-gates nat;
add chain ctfr-gates nat {
    type nat hook postrouting priority srcnat; policy accept;
    iifname team-cloud ip daddr != 10.0.0.0/8 masquerade comment "Team cloud -> public";
    iifname tt-* oifname team-cloud masquerade comment "Local team -> team cloud";
    ip saddr @t-orga oifname team-cloud masquerade comment "Orga -> team cloud";
} 
add chain ctfr-gates static-input;
delete chain ctfr-gates static-input;
add chain ctfr-gates static-input {
  type filter hook input priority filter; policy drop;
  iifname lo accept;
  iifname cilium_wg* accept comment "k8s pod traffic";
  udp dport 51871 counter accept comment "cilium wireguard";

  tcp dport 2113 accept comment "canary";
  tcp sport 2113 ct direction reply accept comment "canary";

  ip saddr @t-orga accept;
  ip saddr @any-team ip daddr { 10.232.0.0/16 } counter drop comment "Teams should not access data plane";
  ip saddr @any-team ip daddr { 10.233.0.0/16 } counter drop comment "Teams should not access overlay";

  udp dport 50000-50251 accept comment "team wireguard";
  meta l4proto { icmp, ipv6-icmp } accept;
  tcp dport { ssh } accept;

  ip saddr 10.237.0.0/16 accept comment "Allow input from pods";
  ip saddr 10.232.0.0/16 accept comment "Allow dataplane";
  ip saddr 10.233.0.0/16 accept comment "Allow overlay";
  ct state vmap { established : accept, related : accept, invalid : drop } comment "replies";
  counter;
}
```

# Reference TC

```yaml
trafficControl:
  ext:
    default:
      params: rate 200mbit
    classes:
      - params: rate 1800mbit
        match:
          - udp sport 50000-50250
teamTrafficControl:
  default:
    params: rate 1000mbit prio 0
  internal:
    params: rate 1800mbit prio 1
  team:
    original: rate 10mbit prio 1
    reply: rate 10mbit prio 1
    qdisc: netem delay 10ms 2ms distribution paretonormal
  netEntities:
    checkers:
    gameservers:
      params: rate 50mbit prio 0
      qdisc: sfq
```