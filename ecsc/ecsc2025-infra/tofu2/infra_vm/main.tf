terraform {
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "3.0.0"
    }
  }
}

locals {
  default_mtu = 1500
}

locals {
  ethernets = {
    ens3 = {
      match = {
        macaddress = var.ext_port.mac_address
      }
      set-name = "ext"
      mtu      = local.default_mtu
      addresses = [
        for addr in var.ext_port.all_fixed_ips : (
          strcontains(addr, ":") ? "${addr}/128" : "${addr}/32"
        )
      ]
    }
    infra-net = {
      optional : true
      match = {
        macaddress = var.infra_net_port.mac_address
      }
      addresses = [
        "${var.infra_net_port.fixed_ip[0].ip_address}/24"
      ]
      # Use the same MTU for game-net as for wireguard networks
      set-name = "infra-net"
      mtu      = var.game_mtu
      routes = [{
        to  = "10.${var.network_index}.0.0/17"
        via = "10.${var.network_index}.251.254"
        }, {
        to  = "10.${var.network_index}.250.0/24"
        via = "10.${var.network_index}.251.254"
        }
      ]
    }
  }
  netplan = {
    network = {
      version = 2
      # Filter out null-values items, netplan won't like those
      ethernets = {
        for k, v in local.ethernets :
        k => v
        if v != null
      }
    }
  }
}


resource "openstack_compute_instance_v2" "vm" {
  name     = var.name
  image_id = var.image_id

  flavor_name = var.flavor
  key_pair    = var.key_pair

  lifecycle {
    ignore_changes = [user_data, image_id]
  }

  network {
    port           = var.ext_port.id
    access_network = true
  }

  user_data = templatefile("${path.module}/cloud-config-infra.yaml.tftpl",
    {
      netplan = local.netplan
      k3s_config = {
        server     = var.k3s_url,
        token      = var.k3s_token
        node-name  = var.name
        node-label = var.labels
        node-taint = var.taints
      }
    }
  )
}

# Ports is attached manually to ensure OpenStack doesn't create netplan
# config that conflicts with what we generate ourselves
resource "openstack_compute_interface_attach_v2" "infra" {
  port_id     = var.infra_net_port.id
  instance_id = openstack_compute_instance_v2.vm.id
}
