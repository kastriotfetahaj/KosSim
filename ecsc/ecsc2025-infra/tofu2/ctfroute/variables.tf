variable "config" {
  type = object({
    # Just declaring the relevant parts of the ctfroute structure here
    initialState = object({
      routers = list(object({
        id    = string
        teams = list(string)
      }))
      teams = list(object({
        id      = string
        network = string
        vulnbox = string
        gateway = string
        connectivity = object({
          publicKey  = string
          privateKey = string
          port       = number
          peers = list(object({
            allowedIps = string
            privateKey = string
            publicKey  = string
          }))
        })
      }))
    })
  })
}

variable "ipv4_access" {
  type = bool
}

variable "routers" {
  type = list(object({
    team_cloud_ip = string
    ip_v4         = string
    ip_v6         = string
    name          = string
  }))
}

variable "network_index" {
  type = number
}

variable "game_mtu" {
  type = number
}
