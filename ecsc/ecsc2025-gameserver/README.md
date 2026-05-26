> [!NOTE]
> The state published here primarily serves to satisfy your curiosity.<br>
> The documentation provided is instructive, but limited.

# ECSC 2025 Gameserver

This repository contains the gameserver used to organize ECSC 2025.

# Structure

- Central databases: PostgresSQL, Redis, RabbitMQ
- Central gameserver _(folder `controlserver`)_: Tick timer, dispatches checker scripts, calculate ranking and create scoreboard
- Checker script workers _(folder `checker_runner`)_: Run the checker scripts
- Submission Server: Accept flags from the participants
- VPN Server: Wireguard/OpenVPN servers for each team with additional monitoring / IPTables controller / tcpdump.

## Setup

- Setup a PostgreSQL database, a redis database and a RabbitMQ server (see below).
- `make deps`
- `npm install && npm run build`
- Write `config.yaml` (see [config.sample.yaml](config.sample.yaml))
- `alembic upgrade head`

Scoreboard and submission server need additional setup:

- cd scoreboard
- npm install && npm run build
- [Flag submission server build instructions](./flag-submission-server/README.md)

## Run gameserver

`export FLASK_APP=controlserver/app.py` is required for most commands. So is either `run.sh` or `. venv/bin/activate`.

- Main server: `flask run --host=0.0.0.0`
- Celery worker: `celery -A checker_runner.celery_cmd worker -Ofair -E -Q celery,tests,broadcast --concurrency=16 --hostname=ident@%h`
- Celery control panel: `celery -A checker_runner.celery_cmd flower --port=5555`

## Setup RabbitMQ

```shell
# Warning: Binds to all interfaces by default!
apt install rabbitmq-server
rabbitmqctl add_vhost saarctf
rabbitmqctl add_user saarctf 123456789
rabbitmqctl set_permissions -p saarctf saarctf '.*' '.*' '.*'
rabbitmqctl set_user_tags saarctf administrator
rabbitmq-plugins enable rabbitmq_management
systemctl restart rabbitmq-server
```

Repeat if necessary.

## Flags

Current format: `ECSC\{[A-Za-z0-9-_]{32}\}`.
Example: `ECSC{8VHsWgEACAD-_wAAfQScbWZat3KXyYe9}`

The prefix `ECSC` can be changed in `config.yaml`: set `flag_prefix` to something else (4 upper chars only so far).

## Folders

- `controlserver`: The main components (timer, scoreboard, scoring, dispatcher, ...)
- `checker_runner`: The celery worker code running the checker scripts
- `gamelib`

## Configuration

To test, copy [`config.sample.yaml`](config.sample.yaml) to `config.yaml` and adjust if needed.

To deploy, you can use environment variables:

- `CONFIG_FILE` path to config.json/config.yaml file
- Set `SAARCTF_NO_RLIMIT` if you have to run checkers without limit (e.g. Chromium)

## Scoring

The formulas to compute ATK/DEF/SLA scores are documented in the ECSC A/D wiki.
On the gameserver side, there are several factors you can use to adjust scores
(all in `config.json` `"scoring":{...}`):

- `nop_team_id`: you cannot submit flags from this team
- `flags_rounds_valid` (default 10) controls how long flags can be submitted for points
- `off_factor` scale offensive points up/down by this factor
- `def_factor` scale defensive points up/down by this factor
- `sla_factor` scale the SLA multiplier by this factor

The default scoring algorithm is `algorithm:ScoreTickAlgorithmAtklab`.
It uses a monotonic positive formula:

- ATK: valid flag submissions always add positive points.
- DEF: services add defense points in rounds where they are up and no valid flag
  from that team/service was submitted.
- SLA: successful or partially recovering services build a service uptime
  multiplier.

Final ranking uses:

```python
total_score = sum((attack_points + defense_points) * sla for service in services)
```

Suggestions for a small workshop are (0/20/2.5/1.5/1.0).

## ENOFLAG Service Interface

We support [enochecker services](https://github.com/enowars/specification) in alpha state.
How? Configure a service like this:

- `checker_timeout`: your tick time (at least 60 seconds with current code)
- `checker_runner`: `eno:EnoCheckerRunner` or a subclass
- `runner_config`: `{"url": "http://localhost:5008"}`
- `checker_subprocess`: false
- `checker_script_dir`: empty
- `checker_script`: empty

Set as usual:

- `flag_ids`: `custom,custom,...` for every putflag that uses attack_info
  > NO SPACES ALLOWED!
- `num_payloads`: number of flag variants
- `flags_per_tick`: number of flag variants

Checkout `config.sample.yaml`, section `runner`.
Please have enough celery workers available, we suggest teams\*services.

## Developers

For type checking do `make check`.

To prepare unit tests, copy `config.sample.json` to `config.test.json` and configure:

- an empty postgresql database (will be wiped during tests)
- an empty redis database
- a working rabbitmq connection

Then you can do `make test`.
