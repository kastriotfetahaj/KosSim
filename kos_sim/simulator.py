from __future__ import annotations

from dataclasses import asdict
from typing import Dict, List

from .models import Asset, AttackMove, DefenseMove, RoundPlan, RoundResult, Scenario, SimulationReport


class AttackDefenseSimulator:
    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.assets: Dict[str, Asset] = {asset.name: Asset(**asdict(asset)) for asset in scenario.assets}
        self.attacker_score = 0
        self.defender_score = 0
        self._scored_compromise: set[str] = set()

    def run(self) -> SimulationReport:
        round_results: List[RoundResult] = []
        for idx, plan in enumerate(self.scenario.rounds, start=1):
            defenses_applied = self._apply_defenses(plan.defenses)
            attack_events = self._apply_attacks(plan.attacks)
            round_results.append(
                RoundResult(index=idx, defenses_applied=defenses_applied, attack_events=attack_events)
            )

        objective_reached = self.assets[self.scenario.objective_target].compromised
        if objective_reached:
            self.attacker_score += 100
            winner = "attacker"
        else:
            winner = "defender"

        final_state = {
            name: {
                "vulnerability": asset.vulnerability,
                "defense": asset.defense,
                "compromised": int(asset.compromised),
                "isolated": int(asset.isolated),
                "monitoring": asset.monitoring,
            }
            for name, asset in self.assets.items()
        }

        compromised_assets = [name for name, asset in self.assets.items() if asset.compromised]

        return SimulationReport(
            scenario_name=self.scenario.name,
            objective_target=self.scenario.objective_target,
            objective_reached=objective_reached,
            winner=winner,
            attacker_score=self.attacker_score,
            defender_score=self.defender_score,
            compromised_assets=compromised_assets,
            rounds=round_results,
            final_state=final_state,
        )

    def _apply_defenses(self, defenses: List[DefenseMove]) -> List[str]:
        events: List[str] = []
        for defense in defenses:
            if defense.target not in self.assets:
                events.append(f"skip:{defense.action}:{defense.target}:unknown_target")
                continue

            asset = self.assets[defense.target]
            action = defense.action.lower()

            if action == "patch":
                old = asset.vulnerability
                asset.vulnerability = max(0, asset.vulnerability - defense.power)
                self.defender_score += 5
                events.append(f"patch:{asset.name}:{old}->{asset.vulnerability}")
            elif action == "harden":
                old = asset.defense
                asset.defense = min(100, asset.defense + defense.power)
                self.defender_score += 5
                events.append(f"harden:{asset.name}:{old}->{asset.defense}")
            elif action == "monitor":
                old = asset.monitoring
                asset.monitoring = min(100, asset.monitoring + defense.power)
                self.defender_score += 3
                events.append(f"monitor:{asset.name}:{old}->{asset.monitoring}")
            elif action == "isolate":
                asset.isolated = True
                self.defender_score += 7
                events.append(f"isolate:{asset.name}:on")
            elif action == "recover":
                if asset.compromised:
                    asset.compromised = False
                    self.defender_score += 20
                    events.append(f"recover:{asset.name}:success")
                else:
                    events.append(f"recover:{asset.name}:noop")
            else:
                events.append(f"skip:{action}:{asset.name}:unknown_action")

        return events

    def _apply_attacks(self, attacks: List[AttackMove]) -> List[str]:
        events: List[str] = []
        for attack in attacks:
            if attack.target not in self.assets:
                events.append(f"attack:{attack.target}:unknown_target")
                continue

            asset = self.assets[attack.target]
            blocked_reason = self._check_prerequisite_or_isolation(attack.target)
            if blocked_reason:
                self.defender_score += 10
                events.append(f"attack:{attack.target}:blocked:{blocked_reason}")
                continue

            effective_attack = attack.strength + (asset.vulnerability / 2.0)
            effective_defense = asset.defense + asset.monitoring
            success = effective_attack > (effective_defense + 20.0)

            if success:
                asset.compromised = True
                if attack.target not in self._scored_compromise:
                    self.attacker_score += 25
                    self._scored_compromise.add(attack.target)
                events.append(
                    f"attack:{attack.target}:success:{attack.technique}:atk={effective_attack:.1f}:def={effective_defense:.1f}"
                )
            else:
                self.defender_score += 10
                events.append(
                    f"attack:{attack.target}:failed:{attack.technique}:atk={effective_attack:.1f}:def={effective_defense:.1f}"
                )

        return events

    def _check_prerequisite_or_isolation(self, target: str) -> str:
        asset = self.assets[target]
        if asset.isolated:
            return "isolated"

        required = self.scenario.prerequisite_path.get(target)
        if required and not self.assets[required].compromised:
            return f"missing_prerequisite:{required}"

        return ""

