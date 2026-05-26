> [!NOTE]
> The state published here primarily serves to satisfy your curiosity.<br>
> The documentation provided is instructive, but limited.

Vulnbox Hosting
===============

This project gets a VM "state" from the [platform](../ecsc2025-platform)
and tries to (re)build vulnboxes according to that state.
If another state is given later, only differences are adjusted.

Configuration
-------------

1. Configure backends (a VM type/kind) in `backends.json`.
   The format depends on the actual backend.
2. Get a state json file (see [format.json](docs/format.json) for an example). 
   The gameserver has a simple script to generate such a state, hosting a vulnbox for each team.
3. To run against state file locally: `uv run -m vulnhost.run`
4. Alternatively for HTTP API: `uv run run_remote`

Backends
--------
Backends configured in `backends.json` are a dict: `{"name": {...}}`.
There will be different backends available, for now it's podman and hetzner cloud.

### Podman Backend
Podman is good to host very light VMs, including SSH and Wireguard. 
Isolation should be good enough for internal use. 
Vulnbox builder can create matching podman images.

Example configuration:
```json
{
  "samplepod": {
    "backend": "podman",
    "container_name": "testbox",
    "image": "vulnbox-image",
    "additional_args": ["--device", "/dev/net/tun", "--cap-add", "NET_ADMIN"],
    "sudo": true
  },

  "config_url": "<url for run_remote.py to pull config from>",
  "status_url": "<url for run_remote.py to report status>"
}
```

### Hetzner Cloud Backend
Example configuration:
```json
{
  "sample_hetzner": {
    "backend": "hetzner",
    "token": "<...>",
    "server_name": "vulnbox",
    "server_type": "cx11",
    "image_name": "vulnbox-setup",
    "ssh_private_key": "/orga/key/id_rsa",
    "firewall": "Allow SSH/VPN Only"
  },

  "config_url": "<url for run_remote.py to pull config from>",
  "status_url": "<url for run_remote.py to report status>"
}
```

### OVH Cloud Backend
Example configuration:
```json
{
    "vulnbox": {
        "backend": "ovhcloud",
        "server_name": "ecsc25-vulnbox",
        "image_id": "...",
        "flavor_name": "c3-32"
    },
    "config_url": "...",
    "status_url": "...",
    "statistics_url": "",
    "statistics_interval": 60
}
```

