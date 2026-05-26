terraform {
  required_version = ">= 1.0"
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 3.0.0"
    }
  }
  backend "local" {
    path = "${path.module}/${var.ctf_name}.tfstate"
  }
}

provider "openstack" {
  auth_url                      = "https://auth.cloud.ovh.net/v3/"
  application_credential_id     = var.credential_id
  application_credential_secret = var.credential_secret
  region                        = var.region
  max_retries                   = 10
}

locals {
  ctf_label = "ctfr.attacking-lab.com/ctf=${var.ctf_name}"
  # Used to balance longhorn replicas into the core
  zone_label = "topology.kubernetes.io/zone=ctf"
  ctf_taint  = "ctfr.attacking-lab.com/ctf=${var.ctf_name}:NoExecute"
  checker_names = [
    for i in range(var.checkers.num) : "checker-${i + 1}"
  ]
  effective_checker_flavors = {
    for name in local.checker_names :
    name => lookup(var.checkers.overrides, name, var.checkers.flavor)
  }
}

module "network" {
  source = "./network"

  ctf_name          = var.ctf_name
  network_index     = var.network_index
  num_routers_team  = var.num_routers_team
  num_routers_infra = var.num_routers_infra
  num_workers       = var.num_workers
  num_gameservers   = var.num_gameservers
  num_checkers      = length(local.checker_names)
  num_observers     = var.num_observers
}

module "pcap_vol" {
  source = "./pcap_vols"

  ctf_name          = var.ctf_name
  num_routers_team  = var.num_routers_team
  num_routers_infra = var.num_routers_infra
  pcap_volumes      = var.pcap_volumes
}

module "router_team" {
  source = "./router_vm"
  count  = var.num_routers_team_vm

  # TODO: Align ctfroute confgen to router-team-X convention
  name = "${var.ctf_name}-router-${count.index + 1}"

  ext_port        = module.network.ext_ports.router_team[count.index]
  data_plane_port = module.network.data_plane_ports.router_team[count.index]
  team_cloud_port = module.network.team_cloud_ports.router_team[count.index]
  pcap_volume     = var.pcap_volumes.size == 0 ? null : module.pcap_vol.pcap_team_volumes[count.index]

  key_pair = var.main_ssh_key_name

  game_mtu = var.game_mtu

  flavor    = var.flavor_routers
  k3s_token = var.k3s_token
  k3s_url   = var.k3s_url
  labels = [
    "ctfr.attacking-lab.com/role=router",
    "ctfr.attacking-lab.com/router-kind=team",
    local.ctf_label,
    local.zone_label
  ]
  taints = [
    "ctfr.attacking-lab.com/role=router:NoExecute",
    local.ctf_taint
  ]
}

module "router_infra" {
  source = "./router_vm"
  count  = var.num_routers_infra_vm

  name = "${var.ctf_name}-router-infra-${count.index + 1}"

  ext_port        = module.network.ext_ports.router_infra[count.index]
  data_plane_port = module.network.data_plane_ports.router_infra[count.index]
  infra_net_port  = module.network.infra_ports.router_infra[count.index]
  pcap_volume     = var.pcap_volumes.size == 0 ? null : module.pcap_vol.pcap_infra_volumes[count.index]

  key_pair = var.main_ssh_key_name

  game_mtu = var.game_mtu

  flavor    = var.flavor_routers
  k3s_token = var.k3s_token
  k3s_url   = var.k3s_url
  labels = [
    "ctfr.attacking-lab.com/role=router",
    "ctfr.attacking-lab.com/router-kind=infra",
    local.ctf_label,
    local.zone_label
  ]
  taints = [
    "ctfr.attacking-lab.com/role=router:NoExecute",
    local.ctf_taint
  ]
}

module "worker" {
  source = "./router_vm"
  count  = var.num_workers_vm

  name = "${var.ctf_name}-worker-${count.index + 1}"

  ext_port        = module.network.ext_ports.worker[count.index]
  data_plane_port = module.network.data_plane_ports.worker[count.index]

  key_pair = var.main_ssh_key_name

  game_mtu = var.game_mtu

  flavor    = var.flavor_workers
  k3s_token = var.k3s_token
  k3s_url   = var.k3s_url
  labels = [
    "ctfr.attacking-lab.com/role=worker",
    local.ctf_label,
    local.zone_label
  ]
  taints = [
    "ctfr.attacking-lab.com/role=worker:NoExecute",
    local.ctf_taint
  ]
  /*
  pcap_volume = var.pcap_volume != null ? {
    type = var.pcap_volume.type
    size = local.router_pcap_size["router-${count.index + 1}"]
  } : null
*/
}

data "openstack_images_image_v2" "gameserver" {
  tags        = [var.gameserver_image_tag]
  most_recent = true
  visibility  = "private"
}

module "gameserver" {
  source = "./infra_vm"
  count  = var.num_gameservers_vm

  name     = "${var.ctf_name}-gameserver-${count.index + 1}"
  image_id = data.openstack_images_image_v2.gameserver.id
  flavor   = var.flavor_gameservers
  key_pair = var.main_ssh_key_name

  ext_port       = module.network.ext_ports.gamserver[count.index]
  infra_net_port = module.network.infra_ports.gameserver[count.index]
  game_mtu       = var.game_mtu
  network_index  = var.network_index

  k3s_token = var.k3s_token
  k3s_url   = var.k3s_url
  labels = [
    # Not labeled worker, don't want no elastic / worker workloads
    # "ctfr.attacking-lab.com/role=worker",
    (
      count.index == 0
      ? "ctfr.attacking-lab.com/gameserver=primary"
      : "ctfr.attacking-lab.com/gameserver=secondary"
    ),
    local.ctf_label,
    local.zone_label
  ]
  taints = [
    "ctfr.attacking-lab.com/role=worker:NoExecute",
    local.ctf_taint
  ]
}

data "openstack_images_image_v2" "checker" {
  tags        = [var.checker_image_tag]
  most_recent = true
  visibility  = "private"
}

module "checker" {
  source = "./infra_vm"
  count  = min(length(local.checker_names), var.checkers.num_vm)

  name     = "${var.ctf_name}-${local.checker_names[count.index]}"
  image_id = data.openstack_images_image_v2.checker.id
  key_pair = var.main_ssh_key_name

  ext_port       = module.network.ext_ports.checker[count.index]
  infra_net_port = module.network.infra_ports.checker[count.index]
  game_mtu       = var.game_mtu
  network_index  = var.network_index

  flavor    = local.effective_checker_flavors[local.checker_names[count.index]]
  k3s_token = var.k3s_token
  k3s_url   = var.k3s_url
  labels = [
    "ctfr.attacking-lab.com/role=infra",
    "ctfr.attacking-lab.com/checker=true",
    local.ctf_label,
    local.zone_label
  ]
  taints = [
    "ctfr.attacking-lab.com/role=infra:NoExecute",
    local.ctf_taint
  ]
}

module "observer" {
  source   = "./infra_vm"
  count    = var.num_observers_vm
  name     = "${var.ctf_name}-observer-${count.index + 1}"
  image_id = data.openstack_images_image_v2.checker.id
  key_pair = var.main_ssh_key_name

  ext_port       = module.network.ext_ports.observer[count.index]
  infra_net_port = module.network.infra_ports.observer[count.index]
  game_mtu       = var.game_mtu
  network_index  = var.network_index

  flavor    = var.flavor_observers
  k3s_token = var.k3s_token
  k3s_url   = var.k3s_url
  labels = [
    "ctfr.attacking-lab.com/role=infra",
    "ctfr.attacking-lab.com/observer=true",
    "ctfr.attacking-lab.com/infra-egress=true",
    local.ctf_label,
    local.zone_label
  ]
  taints = [
    "ctfr.attacking-lab.com/role=infra:NoExecute",
    local.ctf_taint
  ]
}
