data "openstack_images_image_v2" "vulnbox" {
  tags        = [var.vulnbox_image_tag]
  most_recent = true
  visibility  = "private"
}

locals {
  team_ids = [
    for team in module.ctfroute.player_teams : team.id
  ]
  team_ids_numeric = [
    for id in local.team_ids : parseint(id, 10)
  ]
  team_resource_index = [
    for id in local.team_ids_numeric : (id - 1)
  ]
}

module "vulnbox" {
  source = "./vulnbox"
  count  = min(var.max_num_vulnboxes, length(local.team_ids))

  name            = "${var.ctf_name}-vulnbox-${local.team_ids[count.index]}"
  network_index   = var.network_index
  team_network_id = local.team_ids_numeric[count.index]

  image_id = data.openstack_images_image_v2.vulnbox.id
  key_pair = var.main_ssh_key_name
  flavor   = var.flavor_vulnboxes

  team_cloud_network = module.network.team_cloud.network[local.team_resource_index[count.index]]
  wireguard_conf     = module.ctfroute.vulnbox_wg_conf[local.team_ids[count.index]]
}
