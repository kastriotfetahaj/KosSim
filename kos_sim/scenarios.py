from __future__ import annotations

from .models import Asset, AttackMove, DefenseMove, RoundPlan, Scenario


def defender_playbook() -> Scenario:
    return Scenario(
        name="defender_playbook",
        objective_target="db",
        assets=[
            Asset(name="web", vulnerability=70, defense=35),
            Asset(name="app", vulnerability=65, defense=30),
            Asset(name="db", vulnerability=60, defense=40),
        ],
        prerequisite_path={"app": "web", "db": "app"},
        rounds=[
            RoundPlan(
                defenses=[
                    DefenseMove(action="patch", target="web", power=40),
                    DefenseMove(action="harden", target="web", power=30),
                    DefenseMove(action="monitor", target="web", power=20),
                ],
                attacks=[AttackMove(target="web", strength=80, technique="rce")],
            ),
            RoundPlan(
                defenses=[
                    DefenseMove(action="patch", target="app", power=30),
                    DefenseMove(action="harden", target="app", power=25),
                ],
                attacks=[AttackMove(target="app", strength=70, technique="credential_stuffing")],
            ),
            RoundPlan(
                defenses=[DefenseMove(action="isolate", target="db", power=100)],
                attacks=[AttackMove(target="db", strength=75, technique="sql_injection")],
            ),
        ],
    )


def attacker_chain() -> Scenario:
    return Scenario(
        name="attacker_chain",
        objective_target="db",
        assets=[
            Asset(name="web", vulnerability=70, defense=35),
            Asset(name="app", vulnerability=65, defense=30),
            Asset(name="db", vulnerability=60, defense=40),
        ],
        prerequisite_path={"app": "web", "db": "app"},
        rounds=[
            RoundPlan(
                defenses=[DefenseMove(action="monitor", target="web", power=10)],
                attacks=[AttackMove(target="web", strength=85, technique="rce")],
            ),
            RoundPlan(
                defenses=[DefenseMove(action="patch", target="app", power=10)],
                attacks=[AttackMove(target="app", strength=80, technique="token_replay")],
            ),
            RoundPlan(
                defenses=[DefenseMove(action="harden", target="db", power=10)],
                attacks=[AttackMove(target="db", strength=80, technique="privilege_escalation")],
            ),
        ],
    )


SCENARIO_BUILDERS = {
    "defender_playbook": defender_playbook,
    "attacker_chain": attacker_chain,
}

