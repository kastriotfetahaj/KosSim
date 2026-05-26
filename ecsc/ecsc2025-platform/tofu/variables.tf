terraform {
  required_providers {
    hcloud = {
      source = "hetznercloud/hcloud"
    }
  }
  required_version = ">= 1"
}

variable "hcloud_token" {
  sensitive = true
}

variable "datacenter" {
  type    = string
  default = "fsn1-dc14"
}

variable "webpage_size" {
  type    = string
  default = "cx22"
}

variable "ssh_keys" {
  type = list(string)
  default = ["niklas", "simon"]
}