variable "hcloud_token" {
  description = "Hetzner Cloud API token."
  type        = string
  sensitive   = true
}

variable "competition_name" {
  description = "Name prefix for all resources."
  type        = string
  default     = "kossim"
}

variable "location" {
  description = "Hetzner location (e.g., fsn1, nbg1, hel1)."
  type        = string
  default     = "fsn1"
}

variable "network_zone" {
  description = "Hetzner network zone."
  type        = string
  default     = "eu-central"
}

variable "private_cidr" {
  description = "Private network CIDR for all competition components."
  type        = string
  default     = "10.80.0.0/16"
}

variable "team_count" {
  description = "How many team hosts to create."
  type        = number
  default     = 2
}

variable "service_push_secret" {
  description = "Shared secret used by rotator to push flags to service containers."
  type        = string
  sensitive   = true
}

variable "postgres_password" {
  description = "Postgres password for the control-plane database."
  type        = string
  sensitive   = true
}

variable "secret_flag_key" {
  description = "HMAC secret used to sign and verify competition flags."
  type        = string
  sensitive   = true
}

variable "admin_password" {
  description = "Admin panel password."
  type        = string
  sensitive   = true
}

variable "admin_session_secret" {
  description = "Secret used to sign admin session cookies."
  type        = string
  sensitive   = true
}

variable "game_admin_token" {
  description = "Bearer token for legacy/internal game control APIs."
  type        = string
  sensitive   = true
}

variable "repo_url" {
  description = "Git repo URL that contains this project."
  type        = string
  default     = "https://github.com/example/KosSim.git"
}

variable "repo_ref" {
  description = "Git branch/tag/sha to deploy."
  type        = string
  default     = "main"
}

variable "image" {
  description = "Server image."
  type        = string
  default     = "ubuntu-24.04"
}

variable "control_server_type" {
  description = "Server type for control-plane host."
  type        = string
  default     = "cpx21"
}

variable "team_server_type" {
  description = "Server type for each team host."
  type        = string
  default     = "cpx21"
}

variable "nop_server_type" {
  description = "Server type for NOP host."
  type        = string
  default     = "cpx21"
}

variable "control_api_port" {
  description = "Public scoreboard/submit API port on control-plane host."
  type        = number
  default     = 8088
}

variable "team_service_base_port" {
  description = "Team service host ports become base+1..base+5."
  type        = number
  default     = 22000
}

variable "nop_service_base_port" {
  description = "NOP service host ports become base+1..base+5."
  type        = number
  default     = 23000
}

variable "ssh_public_keys" {
  description = "SSH public keys allowed on servers."
  type        = list(string)
  default     = []
}

variable "admin_ssh_cidrs" {
  description = "Source CIDRs allowed to SSH into hosts."
  type        = list(string)
  default     = ["127.0.0.1/32"]
}

variable "vpn_server_type" {
  description = "Server type for dedicated VPN host."
  type        = string
  default     = "cpx11"
}

variable "vpn_udp_port" {
  description = "WireGuard UDP port."
  type        = number
  default     = 51820
}

variable "vpn_allowed_cidrs" {
  description = "Source CIDRs allowed to connect to VPN UDP port."
  type        = list(string)
  default     = ["127.0.0.1/32"]
}

variable "vpn_client_cidr" {
  description = "VPN client address pool CIDR."
  type        = string
  default     = "10.90.0.0/16"
}

variable "vpn_users_per_team" {
  description = "How many VPN user profiles to generate for each team."
  type        = number
  default     = 5
}
