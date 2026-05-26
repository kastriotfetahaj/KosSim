provider "hcloud" {
  token = var.hcloud_token
}

resource "hcloud_firewall" "plsnopwn" {
  name = "plsnopwn"
  # Allow ICMP
  rule {
    direction = "in"
    protocol  = "icmp"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
  # Allow SSH
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "22"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
  # Allow HTTP
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "80"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
  # Allow HTTPs
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "443"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
}

data "hcloud_primary_ip" "ctf_saarland" {
  name = "ctf.saarland"
}

data "hcloud_image" "docker_image" {
  with_selector = "name=docker"
  most_recent   = true
}

resource "hcloud_server" "webpage" {
  name        = "webpage"
  datacenter  = var.datacenter
  image       = data.hcloud_image.docker_image.id
  server_type = var.webpage_size
  ssh_keys    = var.ssh_keys
  public_net {
    ipv4_enabled = true
    ipv4         = data.hcloud_primary_ip.ctf_saarland.id
  }
  lifecycle {
    ignore_changes = [ssh_keys]
  }
  firewall_ids = [hcloud_firewall.plsnopwn.id]
}


