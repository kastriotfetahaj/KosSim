[← README](../README.md) · [Architecture](architecture.md) · [Challenges](challenges.md) · [Data Schema](schema.md) · [Local Runbook](local-runbook.md) · [Hetzner Runbook](hetzner-runbook.md)

---

# Hetzner IaC Runbook

This runbook describes how to deploy the same architecture used locally into Hetzner using Terraform, including team VPN onboarding.

## Infrastructure Components: What and Why

| Component | What It Does | Why It Is Needed |
| --- | --- | --- |
| Control-plane VPS | Runs scoreboard, submit API, flag rotator, and PostgreSQL. | Central authority for round generation and scoring consistency. |
| Team VPS hosts | Run 5 service containers plus team NAT gateway per host. | Isolates each team runtime while preserving equivalent challenge surface. |
| NOP VPS host | Runs always-on non-scoring service set. | Safe testing target for organizers and diagnostics. |
| WireGuard VPN VPS | Creates team client profiles and tunnels into private network. | Secure remote access without exposing internal services publicly. |
| Private network | Connects all hosts for control traffic and service reachability. | Provides deterministic low-latency competition network domain. |

## Prerequisites

- Terraform `>=1.6`
- Hetzner Cloud API token
- SSH public key(s)
- Git repository URL for this project

## Example `terraform.tfvars`

```
hcloud_token         = "YOUR_HCLOUD_TOKEN"
competition_name     = "kossim-prod"
repo_url             = "https://github.com/your-org/KosSim.git"
repo_ref             = "main"
postgres_password    = "replace-with-strong-database-password"
service_push_secret  = "replace-with-strong-service-secret"
secret_flag_key      = "replace-with-strong-flag-hmac-secret"
admin_password       = "replace-with-strong-admin-password"
admin_session_secret = "replace-with-strong-session-secret"
game_admin_token     = "replace-with-strong-admin-api-token"
team_count           = 10
vpn_users_per_team   = 5
ssh_public_keys = [
  "ssh-ed25519 AAAA.... you@example"
]
admin_ssh_cidrs = ["YOUR_PUBLIC_IP/32"]
vpn_allowed_cidrs = ["TEAM_OR_OPERATOR_PUBLIC_CIDR"]
```

### Deploy

**What:** Create all cloud resources and bootstrap compose stacks.

**Why:** Repeatable provisioning with one command flow.

```bash
cd infra/terraform/hetzner
terraform init
terraform plan
terraform apply
```

### Access

**What:** Use control-plane public IP for scoreboard and submit API.

**Why:** Verifies deployment health before teams join.

- `http://<control_public_ipv4>:8088/scoreboard`
- `http://<control_public_ipv4>:8088/api/v1/scoreboard`
- `http://<control_public_ipv4>:8088/api/v1/flags/submit`

## VPN Onboarding

After apply, collect outputs and distribute team client profiles.

```bash
terraform output vpn_public_ipv4
terraform output vpn_udp_port
scp root@<vpn_public_ipv4>:/etc/wireguard/clients/team1/team1-user1.conf .
```

Optional QR output on VPN server:

```bash
ssh root@<vpn_public_ipv4> "qrencode -t ansiutf8 < /etc/wireguard/clients/team1/team1-user1.conf"
```

## Scoring Defaults (Production)

- Tick length: `60s` via `ROTATION_SECONDS`.
- Accepted cap: unlimited when `MAX_ACCEPTED_PER_TEAM_PER_ROUND=0`.
- Attack: each captured flag is worth a fixed value (base `10` divided by the number of flag stores for the service), cumulative and non-decaying.
- Defense and SLA: calculated from retained flag availability and checker health across the retention window.

## NAT Identity Requirement

**What:** Team-originated attacks should appear from team NAT/host IP, not internal container IP.

**Why:** Keeps source identity model realistic and consistent with production-like routing.

**How:** Each team host is provisioned as a kernel NAT gateway by cloud-init — it enables `net.ipv4.ip_forward` and installs a persistent `iptables` rule `POSTROUTING -d <private_cidr> ! -s <private_cidr> -j SNAT --to-source <team_private_ip>`. This masks *all protocols* (TCP, UDP, ICMP, raw) leaving the host toward the competition network as the team's private IP. The rule is inserted at the top of `POSTROUTING` so it takes precedence over Docker's per-bridge masquerade, and saved with `netfilter-persistent` so it survives reboot.

## Destroy

```bash
terraform destroy
```
