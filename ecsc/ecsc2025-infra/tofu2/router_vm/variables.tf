variable "name" {
  type = string
}

variable "pcap_volume" {
  type = object({
    id = string
  })
  default = null
}

variable "flavor" {
  type = string
}

variable "key_pair" {
  type    = string
  default = null
}

variable "ext_port" {
  type = object({
    id            = string
    mac_address   = string
    all_fixed_ips = list(string)
  })
}

variable "data_plane_port" {
  type = object({
    id            = string
    mac_address   = string
    all_fixed_ips = list(string)
    fixed_ip = list(object({
      ip_address = string
    }))
  })
}

variable "infra_net_port" {
  type = object({
    id            = string
    mac_address   = string
    all_fixed_ips = list(string)
    fixed_ip = list(object({
      ip_address = string
    }))
  })
  default = null
}

variable "team_cloud_port" {
  type = object({
    id            = string
    mac_address   = string
    all_fixed_ips = list(string)
    fixed_ip = list(object({
      ip_address = string
    }))
  })
  default = null
}

variable "game_mtu" {
  type = number
}

variable "labels" {
  type = list(string)
}

variable "taints" {
  type = list(string)
}

variable "k3s_token" {
  type      = string
  sensitive = true
}

variable "k3s_url" {
  type = string
}
