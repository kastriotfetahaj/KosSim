# Scoring Formula

The A/D scoreboard is based on attack, defense, and service uptime:

- **ATK** rewards valid flags submitted by a team.
- **DEF** rewards services that are up and were not hacked in the current round.
- **SLA** is a service uptime multiplier.

The total formula is:

```python3
total_score = sum((atk_total + def_total) * sla_multiplier for service in services)
```

Scores are monotonic in ATK and DEF: teams do not lose already-earned attack or
defense points because another team submits a flag later.

## Checker Status

The checker returns one of the following results for each service:

- <span class=hl-success>`SUCCESS`</span> if all flags could be successfully deployed and
  retrieved, and functionality checks were successful.
- <span class=hl-recovering>`RECOVERING`</span> if all checks for the current round succeed,
  but some flags from the retention window are missing.
- <span class=hl-mumble>`MUMBLE`</span> if any functionality checks for the current round failed.
- <span class=hl-offline>`OFFLINE`</span> if the checker failed to establish a connection to the service.
- <span class=hl-error>`INTERNAL_ERROR`</span> if an internal error occurred. **Please notify us with context in a ticket.**

## Constants

```python3
BASE_ATTACK_POINTS = 10.0
BASE_DEFENSE_POINTS = 5.0
flagstores = max(service.flags_per_tick, 1)
```

The configured factors `off_factor`, `def_factor`, and `sla_factor` multiply
their respective components. `sla_factor` scales the SLA multiplier.

## Service Health

`SUCCESS` gives full credit. `RECOVERING` gives partial credit based on how many
valid flags were retrievable in the retention window. All other statuses give no
SLA or DEF credit for that service in that round.

```python3
def service_health(status: str, ok_flags: int, expected_flags: int):
    if status == "SUCCESS":
        return 1.0
    if status == "RECOVERING":
        return ok_flags / max(expected_flags, 1)
    return 0.0
```

## Attack Points

Every valid flag submission gives positive ATK points to the submitting team.
Flags from the NOP team, flags submitted by the NOP team, self-submitted flags,
and expired flags do not score.

The point value is fixed per service and flag store.

```python3
def attack_points(flagstores: float):
    return off_factor * BASE_ATTACK_POINTS / flagstores
```

If two teams submit the same flag, both receive the same positive value. Earlier
submitters are not clawed back when later teams submit the same flag.

## SLA Multiplier

SLA is the running average service health, multiplied by `sla_factor`.

```python3
def sla_multiplier(previous_sla: float, tick: int, current_health: float):
    return ((previous_sla * (tick - 1)) + current_health * sla_factor) / tick
```

## Defense Points

DEF points are awarded every round for each service that is up and was not hacked
in that round. A service is considered hacked for the round if any valid flag
from that team and service is submitted in that round.

```python3
def defense_points(was_hacked: bool, is_up: bool, flagstores: float):
    if was_hacked or not is_up:
        return 0.0
    return def_factor * BASE_DEFENSE_POINTS * flagstores
```

The NOP team does not receive ATK or DEF points.

## Total Points

The gameserver stores cumulative per-service ATK and DEF totals. SLA is applied
as a multiplier:

```python3
service_score = atk_total + def_total
team_score = sum(service_score * sla_multiplier for service in services)
```

The scoreboard rank is computed from `team_score`.

## FAQ

??? question "Why did our team not receive DEF points this round?"

    DEF points require the service to be up and not hacked in the current round.
    If any valid flag from that team and service was submitted in the round, the
    DEF component for that service is zero for that round.

??? question "Can our ATK or DEF points go down later?"

    No. The scoring formula is monotonic. Later submissions of the same valid
    flag receive the same fixed ATK value and do not reduce points already
    awarded to earlier submitters.

??? question "Do expired flags affect DEF?"

    No. Expired, self-submitted, and NOP-related flags are ignored for both ATK
    and the hacked/not-hacked DEF decision.
