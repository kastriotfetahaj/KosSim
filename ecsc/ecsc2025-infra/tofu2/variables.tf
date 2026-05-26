# Auth
variable "credential_id" {
  type      = string
  sensitive = true
}

variable "credential_secret" {
  type      = string
  sensitive = true
}

# CTF
variable "ctfroute_values" {
  type = string
}

variable "ctf_name" {
  type = string
}

variable "network_index" {
  type = number
}

variable "game_mtu" {
  type    = number
  default = 1420
}

variable "ipv4_access" {
  type    = bool
  default = false
}

variable "max_num_vulnboxes" {
  type = number
}

variable "flavor_vulnboxes" {
  type = string
}

variable "num_routers_team" {
  type = number
}

variable "num_routers_team_vm" {
  type = number
}

variable "num_routers_infra" {
  type = number
}

variable "num_routers_infra_vm" {
  type = number
}

variable "flavor_routers" {
  type = string
}

variable "pcap_volumes" {
  type = object({
    type = string
    size = number
    # E.g: router-1: 100, router-infra-1: 100
    overrides = map(number)
  })
  default = {
    type      = "high-speed"
    size      = 0
    overrides = {}
  }
}

variable "num_workers" {
  type = number
}

variable "num_workers_vm" {
  type = number
}

variable "flavor_workers" {
  type = string
}

variable "num_gameservers" {
  type = number
}

variable "num_gameservers_vm" {
  type = number
}

variable "flavor_gameservers" {
  type = string
}

variable "gameserver_image_tag" {
  type    = string
  default = "ecsc-gameserver"
}

variable "checkers" {
  type = object({
    num    = number
    num_vm = number
    flavor = string
    # E.g: checker-1: "c3-128"
    overrides = map(string)
  })
  default = {
    num       = 0
    num_vm    = 0
    flavor    = "c3-32"
    overrides = {}
  }
}

variable "checker_image_tag" {
  type = string
}

variable "vulnbox_image_tag" {
  type = string
}

variable "num_observers" {
  type    = number
  default = 1
}

variable "num_observers_vm" {
  type = number
}

variable "flavor_observers" {
  type    = string
  default = "c3-4"
}

# Cloud Provider Stuff
variable "region" {
  type = string
}

variable "main_ssh_key_name" {
  type = string
}

# Kubernetes
variable "k3s_token" {
  type      = string
  sensitive = true
}

variable "k3s_url" {
  type    = string
  default = "https://gartenverein-tackenberg.de:6443"
}

