terraform {
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "3.0.0"
    }
  }
}

data "openstack_images_image_v2" "router" {
  tags        = ["ecsc-router"]
  most_recent = true
  visibility  = "private"
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
    data-plane = {
      optional : true
      match = {
        macaddress = var.data_plane_port.mac_address
      }
      set-name = "data-plane"
      mtu      = local.default_mtu
      addresses = [
        "${var.data_plane_port.fixed_ip[0].ip_address}/24"
      ]
    }
    infra-net = var.infra_net_port == null ? null : {
      optional : true
      match = {
        macaddress = var.infra_net_port.mac_address
      }
      # Use the same MTU for game-net as for wireguard networks
      mtu      = var.game_mtu
      set-name = "infra-net"
      addresses = [
        "${var.infra_net_port.fixed_ip[0].ip_address}/24"
      ]
    }
    team-cloud = var.team_cloud_port == null ? null : {
      optional : true
      match = {
        macaddress = var.team_cloud_port.mac_address
      }
      mtu      = local.default_mtu
      set-name = "team-cloud"
      addresses = [
        "${var.team_cloud_port.fixed_ip[0].ip_address}/24"
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
  name        = var.name
  image_id    = data.openstack_images_image_v2.router.id
  flavor_name = var.flavor
  key_pair    = var.key_pair

  lifecycle {
    ignore_changes = [user_data, image_id]
    # TODO, hack in a force-replace for downscaling
    # replace_triggered_by = [var.router_generation]
  }

  network {
    port           = var.ext_port.id
    access_network = true
  }

  block_device {
    uuid                  = data.openstack_images_image_v2.router.id
    source_type           = "image"
    destination_type      = "local"
    boot_index            = 0
    delete_on_termination = true
  }

  dynamic "block_device" {
    for_each = range(var.pcap_volume == null ? 0 : 1)
    content {
      uuid                  = var.pcap_volume.id
      source_type           = "volume"
      destination_type      = "volume"
      boot_index            = 1
      delete_on_termination = false
    }
  }

  user_data = templatefile("${path.module}/cloud-config-router.yaml.tftpl",
    {
      # Interface config
      netplan = local.netplan
      # pcap volume
      pcaps_uuid = var.pcap_volume == null ? null : var.pcap_volume.id
      # Options for /etc/rancher/k3s/config.yaml
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

# These ports are attached manually to ensure OpenStack doesn't create netplan
# config that conflicts with what we generate ourselves

resource "openstack_compute_interface_attach_v2" "data_plane" {
  port_id     = var.data_plane_port.id
  instance_id = openstack_compute_instance_v2.vm.id
}

resource "openstack_compute_interface_attach_v2" "infra" {
  count       = var.infra_net_port == null ? 0 : 1
  port_id     = var.infra_net_port.id
  instance_id = openstack_compute_instance_v2.vm.id
}

resource "openstack_compute_interface_attach_v2" "team_cloud" {
  count       = var.team_cloud_port == null ? 0 : 1
  port_id     = var.team_cloud_port.id
  instance_id = openstack_compute_instance_v2.vm.id
}
