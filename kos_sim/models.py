from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Asset:
    name: str
    vulnerability: int
    defense: int
    compromised: bool = False
    isolated: bool = False
    monitoring: int = 0


@dataclass
class AttackMove:
    target: str
    strength: int
    technique: str = "generic"


@dataclass
class DefenseMove:
    action: str
    target: str
    power: int


@dataclass
class RoundPlan:
    defenses: List[DefenseMove] = field(default_factory=list)
    attacks: List[AttackMove] = field(default_factory=list)


@dataclass
class Scenario:
    name: str
    objective_target: str
    assets: List[Asset]
    prerequisite_path: Dict[str, str] = field(default_factory=dict)
    rounds: List[RoundPlan] = field(default_factory=list)


@dataclass
class RoundResult:
    index: int
    defenses_applied: List[str]
    attack_events: List[str]


@dataclass
class SimulationReport:
    scenario_name: str
    objective_target: str
    objective_reached: bool
    winner: str
    attacker_score: int
    defender_score: int
    compromised_assets: List[str]
    rounds: List[RoundResult]
    final_state: Dict[str, Dict[str, Optional[int]]]
