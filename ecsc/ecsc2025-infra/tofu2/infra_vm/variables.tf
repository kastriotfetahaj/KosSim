variable "name" {
  type = string
}

variable "image_id" {
  type = string
}

variable "flavor" {
  type = string
}

variable "key_pair" {
  type = string
}

variable "ext_port" {
  type = object({
    id            = string
    mac_address   = string
    all_fixed_ips = list(string)
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
}

variable "network_index" {
  type = number
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
