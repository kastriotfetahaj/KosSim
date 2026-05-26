output "pcap_team_volumes" {
  value = openstack_blockstorage_volume_v3.pcaps_team
}

output "pcap_infra_volumes" {
  value = openstack_blockstorage_volume_v3.pcaps_infra
}
