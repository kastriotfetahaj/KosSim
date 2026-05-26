from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI
from pydantic_settings import BaseSettings

from ctfroute.adapters.yaml_conf import read_yaml_conf
from ctfroute.state.external import CtfRouteState, Gate


class Settings(BaseSettings):
    ctfroute_config: str = "/opt/ctfroute/ctfroute.yml"


settings = Settings()


class StateRef:
    def __init__(self) -> None:
        self.value: CtfRouteState | None = None


STATE = StateRef()


async def get_state() -> CtfRouteState:
    if STATE.value is None:
        config = read_yaml_conf(Path(settings.ctfroute_config))
        STATE.value = config.initial_state
    return STATE.value


State = Annotated[CtfRouteState, Depends(get_state)]
app = FastAPI()


@app.post("/state")
def set_state(new_state: CtfRouteState):
    STATE.value = new_state
    return STATE.value


@app.get("/state")
def get_state(state: State):
    return state


@app.get("/state/gates")
def get_gates(state: State):
    return state.gates


@app.post("/state/gates")
def set_gate(state: State, gates: list[Gate]):
    state.gates = gates
    return state.gates


@app.post("/state/gates/add")
def add_gate(state: State, gate: Gate):
    state.gates.append(gate)
    return gate
