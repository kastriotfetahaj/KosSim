packer {
  required_plugins {
    ansible = {
      source  = "github.com/hashicorp/ansible"
      version = "~> 1"
    }
  }
}

locals { timestamp = regex_replace(timestamp(), "[- TZ:]", "") }

source "hcloud" "ecsc-vulnbox" {
  image       = "ubuntu-24.04"
  location    = "fsn1"
  server_type = "cpx21"
  snapshot_labels = {
    type = "ecsc-vulnbox-real"
  }
  snapshot_name           = "ecsc-vulnbox-real-${local.timestamp}"
  ssh_username            = "root"
  temporary_key_pair_type = "ecdsa"
}

build {
  sources = ["source.hcloud.ecsc-vulnbox"]

  provisioner "ansible" {
    ansible_env_vars = ["ANSIBLE_PIPELINING=True", "ANSIBLE_LOG_PATH=/bambictf/logs/router-ansible.log", "ANSIBLE_VERBOSITY=1", "ANSIBLE_LOG_VERBOSITY=1"]
    extra_arguments  = ["--scp-extra-args", "'-O'"]
    host_alias       = "packer-router"
    playbook_file    = "ansible/ecsc-vulnbox.yml"
    user             = "root"
  }

}
