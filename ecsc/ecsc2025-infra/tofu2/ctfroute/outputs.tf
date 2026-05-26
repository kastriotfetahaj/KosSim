output "total_teams" {
  # -1 for orga
  value = length(var.config.initialState.teams) - 1
}

output "player_teams" {
  value = [
    for team in local.available_teams : team
    if team.id != "orga"
  ]
}

output "vulnbox_wg_conf" {
  value = local.vulnbox_wg_conf
}

output "orga_wg_confs" {
  value = local.orga_wg_confs
}

output "webpage_config" {
  value = local.webpage_config
}
