output "instance" {
  value = openstack_compute_instance_v2.vm
}

output "team_cloud_ip" {
  value = var.team_cloud_port == null ? null : var.team_cloud_port.fixed_ip[0].ip_address
}
