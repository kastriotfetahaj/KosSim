data "local_file" "ctfroute_values" {
  filename = "${path.module}/${var.ctfroute_values}"
}

locals {
  router_teams = [
    for i in range(var.num_routers_team) : {
      name = "${var.ctf_name}-router-${i + 1}"
      ip_v4 = one([
        for ip in module.network.ext_ports.router_team[i].all_fixed_ips : ip
        if strcontains(ip, ".")
      ])
      ip_v6 = one([
        for ip in module.network.ext_ports.router_team[i].all_fixed_ips : ip
        if strcontains(ip, ":")
      ])
      team_cloud_ip = module.network.team_cloud_ports.router_team[i].fixed_ip[0].ip_address
    }
  ]
  router_infra = [
    for i in range(var.num_routers_infra) : {
      name = "${var.ctf_name}-router-infra-${i + 1}"
      ip_v4 = one([
        for ip in module.network.ext_ports.router_infra[i].all_fixed_ips : ip
        if strcontains(ip, ".")
      ])
      ip_v6 = one([
        for ip in module.network.ext_ports.router_infra[i].all_fixed_ips : ip
        if strcontains(ip, ":")
      ])
      team_cloud_ip = null
    }
  ]
  routers = concat(local.router_teams, local.router_infra)
}

module "ctfroute" {
  source        = "./ctfroute"
  config        = yamldecode(data.local_file.ctfroute_values.content).ctfroute
  network_index = var.network_index
  game_mtu      = var.game_mtu
  ipv4_access   = var.ipv4_access
  routers       = local.routers
}

locals {
  conf_dir = "${path.module}/generated-config/${var.ctf_name}"
}

resource "local_sensitive_file" "webpage_config" {
  filename = "${local.conf_dir}/webpage_config.json"
  content  = jsonencode(module.ctfroute.webpage_config)
}

resource "local_sensitive_file" "orga_wg_conf" {
  count    = length(module.ctfroute.orga_wg_confs)
  filename = "${local.conf_dir}/orga-vpn/orga-${count.index}.conf"
  content  = module.ctfroute.orga_wg_confs[count.index]
}

resource "local_sensitive_file" "ssh_config" {
  filename = "${local.conf_dir}/ssh_config"
  content = templatefile(
    "${path.module}/ssh_config.tftpl", {
      ipv4_access   = var.ipv4_access
      router_team   = module.router_team
      router_infra  = module.router_infra
      worker        = module.worker
      checker       = module.checker
      gameserver    = module.gameserver
      observer      = module.observer
      ctf_name      = var.ctf_name
      network_index = var.network_index
    }
  )
}

resource "local_sensitive_file" "ansible_inventory" {
  filename = "${local.conf_dir}/inventory.yml"
  content = yamlencode(
    {
      vulnboxes : {
        hosts : {
          for i in range(1, module.ctfroute.total_teams + 1) : "vulnbox-${i}" => {
            ansible_host : "10.${var.network_index + 1}.${i}.2"
          }
        }
        vars : {
          ansible_ssh_private_key_file : "~/.ssh/ecsc_infra"
        }
      }
      routers_team : {
        hosts : {
          for mod in module.router_team : mod.instance.name => {
            ansible_host : (
              var.ipv4_access ? mod.instance.access_ip_v4 : mod.instance.access_ip_v4
            )
          }
        }
      }
      routers_infra : {
        hosts : {
          for mod in module.router_infra : mod.instance.name => {
            ansible_host : (
              var.ipv4_access ? mod.instance.access_ip_v4 : mod.instance.access_ip_v4
            )
          }
        }
      }
      workers : {
        hosts : {
          for mod in module.worker : mod.instance.name => {
            ansible_host : (
              var.ipv4_access ? mod.instance.access_ip_v4 : mod.instance.access_ip_v4
            )
          }
        }
      }
      checkers : {
        hosts : {
          for mod in module.checker : mod.instance.name => {
            ansible_host : (
              var.ipv4_access ? mod.instance.access_ip_v4 : mod.instance.access_ip_v4
            )
          }
        }
      }
      gameservers : {
        hosts : {
          for mod in module.gameserver : mod.instance.name => {
            ansible_host : (
              var.ipv4_access ? mod.instance.access_ip_v4 : mod.instance.access_ip_v4
            )
          }
        }
      }
      observers : {
        hosts : {
          for mod in module.observer : mod.instance.name => {
            ansible_host : (
              var.ipv4_access ? mod.instance.access_ip_v4 : mod.instance.access_ip_v4
            )
          }
        }
      }
      all : {
        vars : {
          ansible_user : "root"
          ansible_ssh_extra_args : "-o StrictHostKeyChecking=no"
        }
      }
    }
  )
}
