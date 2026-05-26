ctf_name        = "staging"
ctfroute_values = "../k8s/events/staging-ctfroute-values.yaml"
# This is not sanity checked, make sure it is aligned with he ctfroute values!
network_index = 32
game_mtu      = 1420

ipv4_access       = true
vulnbox_image_tag = "ecsc-vulnexploiter-real"
max_num_vulnboxes = 4
flavor_vulnboxes  = "c3-8"

num_routers_team  = 4
num_routers_infra = 1
flavor_routers    = "d2-8"
pcap_volumes = {
  type = "classic"
  size = 10
  overrides = {
    router-infra-1 : 20
  }
}

num_workers    = 1
flavor_workers = "r3-32"

num_gameservers    = 1
flavor_gameservers = "c3-8"

checker_image_tag = "ecsc-checker-real"
checkers = {
  num    = 5
  flavor = "c3-8"
  overrides = {
    # heavensent
    checker-5 : "c3-32"
  }
}
