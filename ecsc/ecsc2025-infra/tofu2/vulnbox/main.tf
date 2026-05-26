terraform {
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "3.0.0"
    }
  }
}

resource "openstack_compute_instance_v2" "vulnbox" {
  name        = var.name
  image_id    = var.image_id
  flavor_name = var.flavor
  key_pair    = var.key_pair

  lifecycle {
    ignore_changes = [user_data, image_id]
  }

  network {
    name           = var.team_cloud_network.name
    fixed_ip_v4    = "10.${var.network_index + 1}.${var.team_network_id}.2"
    access_network = true
  }

  user_data = templatefile(
    "${path.module}/cloud-config-vulnbox.yaml.tftpl", {
      wireguard_conf = var.wireguard_conf
    }
  )
}
