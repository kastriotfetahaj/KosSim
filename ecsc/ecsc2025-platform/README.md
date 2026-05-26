> [!NOTE]
> The state published here primarily serves to satisfy your curiosity.<br>
> The documentation provided is instructive, but limited.

# ECSC 2025 Platform

## Setup:

```sh
uv sync --frozen
npm install
uv run python manage.py migrate
# Creates an admin:admin user and a bunch of teams and players with password==username
uv run python manage.py create_test_teams 10

# If you DON'T want to work on Vue.js stuff, build it once and make sure to run it again
# after pulling changes
npx vite build
```

## Starting

```sh
python manage.py runserver # -> Access at port 8000
# If you want to work on Vue.js stuff
npm run dev # -> Access at port 5173
```

## Help, my hot reload is broken!

Django uses the built frontend code (`./vite_build`) as soon as it exists. To prevent
that set `VITE_FORCE_DEV = True` in `settings.py`.

## Configuration

### Runtime

These settings can be modified via django admin (Constance):

- `SHOW_CONFIG`: Team ID is visible, VPN can be configured
- `SHOW_SCOREBOARD`: Show link to scoreboard
- `ENABLE_SIGNUP`: Teams can register
- `ENABLE_ACTIVATION`: Teams can activate their account
- `VPN_HOST` / `VPN_BASE_PORT`: VPN server endpoint (port = base port + team id)
- `HOSTING_ORGA_KEYS`: SSH keys to deploy on every vulnbox (one per line)
- links on the front page:
  - `URL_ROUTER` router VM download link
  - `URL_TESTBOX` testbox VM download link
  - `URL_VULNBOX` vulnbox VM download link
  - `URL_CLOUD` cloud bundle download link
  - `URL_SCOREBOARD` scoreboard link
- If you have cloud hosting configured, you can edit the "control available" dates here

### Env vars:

You can set environment variables to set settings:

- `CONFIG_CONFIG_REPO` : (deprecated) Path to the repository to sync with the infrastructure. Used for database location and OpenVPN configs. Use "None" if this instance is not (yet) connected to a repository.
- `CONFIG_VPN_CONFIG_PATH` : (deprecated) Path to the VPN config directory (can be inferred from CONFIG_REPO)
- `CONFIG_DATABASE` : Django database config as JSON string. Example: `{"ENGINE": "django.db.backends.postgresql_psycopg2", "NAME": "...", "USER": "...", "PASSWORD": "...", "HOST": "localhost"}`
- `REDIS_URL` : (optional) A redis instance if available (example: `redis://user:pass@localhost:6379/0`)
- Cloud hosting config:
  - `CONFIG_HOSTING_ENABLED` : True or False
  - `CONFIG_HOSTING_VM_TEMPLATES` : JSON file with configured VM templates (see examples below)
  - `CONFIG_HOSTING_TOKEN` : A secret token to authorize against other systems (vulnhost, user sync script, ...)
  - `CONFIG_CLOUD_HOSTING_DEFAULT` : True or False - True = new teams will be cloud-hosted, False = new teams will self-host
- PostgreSQL config:
  - `POSTGRES_DB`
  - `POSTGRES_USER`
  - `POSTGRES_PASSWORD`
  - `POSTGRES_HOST` (optional, default `localhost`)
  - `POSTGRES_PORT` (optional, default `5432`)
- Oauth config:
  - `OAUTH_CLIENT_ID`
  - `OAUTH_SECRET`
  - `OAUTH_CONFIG_URL`

### Cloud hosting configuration

Configure cloud hosting with these environment variables, and a JSON file containing a vulnhost template:

```
CONFIG_HOSTING_ENABLED=True
CONFIG_HOSTING_VM_TEMPLATES=vm_templates.json
CONFIG_HOSTING_TOKEN=abcdef
```

Example configuration (`vm_templates.json`):

```json
[
  {
    "name": "Test VM",
    "description": "<...>",
    "ip_suffix": 2,
    "control_available_from": "21.12.2020 20:00:00 UTC",
    "control_available_to": "22.12.2020 20:00:00 UTC",
    "template": {
      "kind": "<kind_name>",
      "sshkey": "{{ssh_keys}}",
      "files": {
        "/etc/wireguard/vulnbox.conf": {
          "content": "{{wireguard_config_file}}",
          "permission": "0600",
          "owner": "root:root"
        }
      },
      "action_counters": { "reboot": 0, "reset": 0, "reset_root_password": 0 },
      "root_password": "{{generate}}"
    }
  }
]
```

Use the `root_password` key only for podman backends, not for Hetzner. Hetzner backend will generate root passwords for you.
If you do not pass the `control_available_*` parameters, you can configure them in Django admin.

To connect the vulnbox hosting tool use these URLs:

```
https://ctf.host/vms/config?token=abcdef
https://ctf.host/vms/status?token=abcdef
```

## Connection to infra

To import teams, use this url and `CONFIG_HOSTING_TOKEN`:

`https://ctf.host/team/export?token=<abc>`

## Deployment

Create a `secrets.tfvars` (copy from `secrets.tfvars.example`) and add a Hetzner cloud token.
In the `packer` directory initialize packer with `packer init docker` and build the image with `packer buid -var-file=secrets.pkvars.hcl docker`.
