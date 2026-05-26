packer {
  required_plugins {
    ansible = {
      source  = "github.com/hashicorp/ansible"
      version = "~> 1"
    }
    hcloud = {
      source  = "github.com/hashicorp/hcloud"
      version = "~> 1"
    }
  }
}

source "hcloud" "base" {
  token         = "${ var.hcloud_token }"
  image         = "debian-12"
  snapshot_name = "docker-{{timestamp}}"
  snapshot_labels = {
    name = "docker"
  }
  location     = "fsn1"
  server_type  = "cx22"
  ssh_username = "root"
}

build {
  sources = [
    "source.hcloud.base"
  ]

  provisioner "ansible" {
    playbook_file = "${path.root}/playbook.yml"
    user          = "root"
    use_proxy     = false
    ansible_env_vars = [
      "ANSIBLE_ROLES_PATH=/roles:/usr/share/ansible/roles:/etc/ansible/roles:${path.root}/../../ansible_playbook/roles"
    ]
  }
}
