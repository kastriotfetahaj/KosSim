variable "num_routers_team" {
  type = number
}

variable "num_routers_infra" {
  type = number
}

variable "ctf_name" {
  type = string
}

variable "pcap_volumes" {
  type = object({
    type      = string
    size      = number
    overrides = map(number)
  })
  default = null
}
