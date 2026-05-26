variable "name" {
  type = string
}

variable "flavor" {
  type = string
}

variable "image_id" {
  type = string
}

variable "key_pair" {
  type    = string
  default = null
}

variable "network_index" {
  type = number
}

variable "team_network_id" {
  type = number
}

variable "team_cloud_network" {
  type = object({
    name = string
    id   = string
  })
}

variable "wireguard_conf" {
  type = string
}
