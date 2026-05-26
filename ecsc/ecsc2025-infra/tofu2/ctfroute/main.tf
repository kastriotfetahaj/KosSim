locals {
  # Map teams to ctfroute router id
  team_router_ids = {
    for team in var.config.initialState.teams :
    team.id => one([
      for router in var.config.initialState.routers : router.id
      if contains(router.teams, team.id)
    ])
  }

  # Hostnames of routers that are actually provisioned
  available_routers = [for router in var.routers : router.name]

  # Teams whose router was - or will be - provisioned
  # This enables provisioning a subset of the routers and teams
  # configured in the ctfroute conf
  available_teams = [
    for team in var.config.initialState.teams : team
    if contains(local.available_routers, local.team_router_ids[team.id])
  ]

  # Modules of routers which teams are mapped to
  team_routers = {
    for team in local.available_teams :
    team.id => one([
      for mod in var.routers : mod
      if mod.name == local.team_router_ids[team.id]
    ])
  }

  game_net       = "10.${var.network_index}.0.0/16"
  team_cloud_net = "10.${var.network_index + 1}.0.0/16"

  router_public_ips = {
    for team in local.available_teams :
    team.id => (
      var.ipv4_access
      ? local.team_routers[team.id].ip_v4
      : local.team_routers[team.id].ip_v6
    )
  }

  router_private_ips = {
    for team in local.available_teams :
    team.id => local.team_routers[team.id].team_cloud_ip
  }

  team_exploiter_ips = {
    for team in local.available_teams :
    team.id => "10.${var.network_index}.${team.id}.3"
  }

  team_cloud_hosted_peers = {
    for team in local.available_teams :
    team.id => ["${team.vulnbox}/32", "${local.team_exploiter_ips[team.id]}/32"]
  }

  webpage_config = {
    game_net = local.game_net
    teams = [
      for team in local.available_teams : {
        id             = team.id
        vpn_host       = local.router_public_ips[team.id]
        vpn_port       = team.connectivity.port
        vpn_public_key = team.connectivity.publicKey
        vulnbox        = team.vulnbox
        gateway        = team.gateway
        exploiter      = local.team_exploiter_ips[team.id]
        peers = [
          for peer in team.connectivity.peers : {
            public_key  = peer.publicKey
            private_key = peer.privateKey
            cidr        = peer.allowedIps
            vpn_host = (
              contains(local.team_cloud_hosted_peers[team.id], peer.allowedIps)
              ? local.router_private_ips[team.id]
              # Don't set the public ip on peers in the DB to ease failover:
              # Only editing the interface is necessary to change all player confs
              : null
            )
            overrides = {
              MTU = var.game_mtu
              AllowedIPs = (
                contains(local.team_cloud_hosted_peers[team.id], peer.allowedIps)
                ? local.game_net
                : join(", ", [local.game_net, local.team_cloud_net, ])
              )
            }
          }
        ]
      }
      if team.id != "orga"
    ]
  }

  # Private key used for the vulnbox peer
  vulnbox_private_keys = {
    for team in local.available_teams :
    team.id => one([
      for peer in team.connectivity.peers : peer.privateKey
      if peer.allowedIps == "${team.vulnbox}/32"
    ])
  }

  vulnbox_wg_data = {
    for team in local.available_teams :
    team.id => {
      PrivateKey = local.vulnbox_private_keys[team.id]
      Address    = team.vulnbox
      MTU        = var.game_mtu
      PublicKey  = team.connectivity.publicKey
      Endpoint   = "${local.router_private_ips[team.id]}:${team.connectivity.port}"
      AllowedIPs = local.game_net
      Comment    = "Vulnbox config for team ${team.id}"
    }
    if team.id != "orga"
  }

  vulnbox_wg_conf = {
    for id, data in local.vulnbox_wg_data :
    id => templatefile("${path.module}/wg.conf.tftpl", local.vulnbox_wg_data[id])
  }

  # Used to provide v4 & v6 to orga
  router_alt_public_ips = {
    for team in local.available_teams :
    team.id => (
      var.ipv4_access
      ? local.team_routers[team.id].ip_v6
      : local.team_routers[team.id].ip_v4
    )
  }

  team_player_wg_data = {
    for team in local.available_teams :
    team.id => [
      for peer in team.connectivity.peers : {
        PrivateKey = peer.privateKey
        Address    = replace(peer.allowedIps, "/\\d\\d$", "")
        MTU        = var.game_mtu
        PublicKey  = team.connectivity.publicKey
        # Players access the router through the public ip!
        Endpoint = "${local.router_public_ips[team.id]}:${team.connectivity.port}"
        AllowedIPs = (
          # Orga may additionally access infra networks
          team.id == "orga"
          ? join(", ", [
            "10.232.${var.network_index}.0/24",
            "10.233.${var.network_index}.0/24",
            local.game_net,
            local.team_cloud_net,
          ])
          : join(", ", [
            local.game_net,
            local.team_cloud_net,
          ])
        )
        Comment = (
          team.id == "orga"
          ? "Alt endpoint: ${local.router_alt_public_ips[team.id]}"
          : "Player config for team ${team.id}"
        )
      }
      if peer.allowedIps != "${team.vulnbox}/32"
    ]
    # Only compute this for orga (speed), remove to re-enable rendering non-orga wg confs
    if team.id == "orga"
  }

  # Rendered team wireguard configs
  team_player_wg_confs = {
    for id, confs in local.team_player_wg_data :
    id => [for conf in confs : templatefile("${path.module}/wg.conf.tftpl", conf)]
    if id != "orga"
  }

  orga_wg_confs = [
    for conf in local.team_player_wg_data["orga"] :
    templatefile("${path.module}/wg.conf.tftpl", conf)
  ]
}
