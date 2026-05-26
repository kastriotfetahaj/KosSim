# Avoid mixing go templating calls ( for example ```{{ upper(`string`) }}``` )
# and HCL2 calls (for example '${ var.string_value_example }' ). They won't be
# executed together and the outcome will be unknown.

# See https://www.packer.io/docs/templates/hcl_templates/blocks/packer for more info
packer {
  required_plugins {
    ansible = {
      source  = "github.com/hashicorp/ansible"
      version = "~> 1"
    }
  }
}

# All generated input variables will be of 'string' type as this is how Packer JSON
# views them; you can change their type later on. Read the variables type
# constraints documentation
# https://www.packer.io/docs/templates/hcl_templates/variables#type-constraints for more info.
variable "ext_net_id" {
  type    = string
  default = "6c928965-47ea-463f-acc8-6d4a152e9745"
}

# "timestamp" template function replacement
locals { timestamp = regex_replace(timestamp(), "[- TZ:]", "") }

# source blocks are generated from your builders; a source can be referenced in
# build blocks. A build block runs provisioner and post-processors on a
# source. Read the documentation for source blocks here:
# https://www.packer.io/docs/templates/hcl_templates/blocks/source
source "openstack" "ecsc-infra" {
  flavor                  = "d2-8"
  image_name              = "ecsc-infra-${local.timestamp}"
  image_tags              = [ "ecsc-infra" ]
  networks                = ["${var.ext_net_id}"]
  source_image_name       = "Debian 12 - UEFI"
  ssh_ip_version          = "4"
  ssh_username            = "debian"
  temporary_key_pair_type = "ecdsa"
  security_groups = [ "packer_sandbox_secgroup" ]
}

# a build block invokes sources and runs provisioning steps on them. The
# documentation for build blocks can be found here:
# https://www.packer.io/docs/templates/hcl_templates/blocks/build
build {
  sources = ["source.openstack.ecsc-infra"]

  provisioner "ansible" {
    ansible_env_vars = ["ANSIBLE_PIPELINING=True", "ANSIBLE_LOG_PATH=/bambictf/logs/router-ansible.log", "ANSIBLE_VERBOSITY=1", "ANSIBLE_LOG_VERBOSITY=1"]
    extra_arguments  = ["--scp-extra-args", "'-O'"]
    host_alias       = "packer-infra"
    playbook_file    = "ansible/ecsc-infra.yml"
    user             = "debian"
  }

}
