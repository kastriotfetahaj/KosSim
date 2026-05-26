ctf_name        = "ecsc"
ctfroute_values = "../k8s/events/ecsc-ctfroute-values.yaml"
network_index   = 42
game_mtu        = 1420

ipv4_access       = false
vulnbox_image_tag = "ecsc-vulnexploiter-real"
max_num_vulnboxes = 0
flavor_vulnboxes  = "c3-32"

num_routers_team     = 41
num_routers_team_vm  = 41
num_routers_infra    = 2
num_routers_infra_vm = 2
flavor_routers       = "b3-32"
pcap_volumes = {
  type = "high-speed"
  size = 30
  overrides = {
    router-18 : 70
    router-11 : 50
    router-29 : 150
    router-9 : 100
    router-infra-1 : 600
  }
}

num_workers    = 3
num_workers_vm = 3
flavor_workers = "r3-64"

num_gameservers    = 2
num_gameservers_vm = 2
flavor_gameservers = "c3-32"

checker_image_tag = "ecsc-checker-real"
checkers = {
  num    = 6
  num_vm = 5
  flavor = "c3-32"
  overrides = {
    # heavensent
    checker-5 : "c3-320"
  }
}

num_observers    = 1
num_observers_vm = 1
