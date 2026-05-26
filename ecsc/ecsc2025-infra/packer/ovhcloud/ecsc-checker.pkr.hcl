packer {
  required_plugins {
    ansible = {
      source  = "github.com/hashicorp/ansible"
      version = "~> 1"
    }
  }
}

variable "ext_net_id" {
  type    = string
  default = "6c928965-47ea-463f-acc8-6d4a152e9745"
}

# "timestamp" template function replacement
locals { timestamp = regex_replace(timestamp(), "[- TZ:]", "") }

source "openstack" "packer-checker-real" {
  flavor                  = "d2-8"
  image_name              = "ecsc-checker-real-${local.timestamp}"
  image_tags              = [ "ecsc-checker-real" ]
  networks                = ["${var.ext_net_id}"]
  # source_image_name       = "ecsc-infra"
  source_image_filter {
    filters {
      tags        = [ "ecsc-infra-trixie" ]
    }
    most_recent = true
  }
  ssh_ip_version          = "4"
  ssh_username            = "debian"
  temporary_key_pair_type = "ecdsa"
  security_groups = [ "packer_sandbox_secgroup" ]
}

build {
  sources = ["source.openstack.packer-checker-real"]

  provisioner "ansible" {
    ansible_env_vars = ["ANSIBLE_PIPELINING=True", "ANSIBLE_LOG_PATH=/bambictf/logs/router-ansible.log", "ANSIBLE_VERBOSITY=1", "ANSIBLE_LOG_VERBOSITY=1"]
    extra_arguments  = ["--scp-extra-args", "'-O'"]
    host_alias       = "packer-checker-real"
    playbook_file    = "ansible/ecsc-checker.yml"
    user             = "debian"
  }

}