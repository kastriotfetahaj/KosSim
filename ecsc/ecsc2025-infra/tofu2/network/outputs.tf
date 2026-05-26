output "data_plane" {
  value = {
    network = openstack_networking_network_v2.data_plane
    subnet  = openstack_networking_subnet_v2.data_plane
  }
}

output "infra" {
  value = {
    network = openstack_networking_network_v2.infra
    subnet  = openstack_networking_subnet_v2.infra
  }
}

output "team_cloud" {
  value = {
    network = openstack_networking_network_v2.team_cloud
    subnet  = openstack_networking_subnet_v2.team_cloud
  }
}

output "ext_ports" {
  value = {
    router_team  = openstack_networking_port_v2.ext_router_team
    router_infra = openstack_networking_port_v2.ext_router_infra
    worker       = openstack_networking_port_v2.ext_worker
    gamserver    = openstack_networking_port_v2.ext_gameserver
    checker      = openstack_networking_port_v2.ext_checker
    observer     = openstack_networking_port_v2.ext_observer
  }
}

output "data_plane_ports" {
  value = {
    router_team  = openstack_networking_port_v2.data_plane_router_team
    router_infra = openstack_networking_port_v2.data_plane_router_infra
    worker       = openstack_networking_port_v2.data_plane_worker
  }
}

output "infra_ports" {
  value = {
    router_infra = openstack_networking_port_v2.infra_router_infra
    gameserver   = openstack_networking_port_v2.infra_gameserver
    checker      = openstack_networking_port_v2.infra_checker
    observer     = openstack_networking_port_v2.infra_observer
  }
}

output "team_cloud_ports" {
  value = {
    router_team = openstack_networking_port_v2.router_team_cloud
  }
}
