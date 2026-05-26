import asyncio
from abc import ABC, abstractmethod
from asyncio import Queue, QueueShutDown
from typing import AsyncGenerator, assert_never

from pydantic import BaseModel

from ctfroute.defs import DEFAULT_MTU
from ctfroute.state import LocalContext
from ctfroute.state.external import GateId, NetEntity, NetEntityId, RouterId, TeamId
from ctfroute.state.internal import (
    ConnGate,
    CtfRouteState,
    Gate,
    RawGate,
    Router,
    Team,
)
from ctfroute.state.utils import InternalState
from ctfroute.utils import EntityType


class InternalUpdate(BaseModel):
    entity_type: EntityType
    entity_id: TeamId | RouterId | GateId
    update: InternalState

    def __str__(self):
        entity_type = self.entity_type.value
        entity_id = self.entity_id
        update = self.update
        return f"Update {entity_type=} {entity_id=} {update=}"


class Controller(ABC):
    def __init__(
        self, initial_state: CtfRouteState, context: LocalContext, *args, **kwargs
    ):
        self.state = initial_state
        self.context = context
        self.updates: Queue[InternalUpdate] = Queue()

    def __str__(self):
        return f"{self.__class__.__name__} on {self.context.self_id}"

    def __init_subclass__(cls, **kwargs):
        """
        Define constants for internal_state entry names.

        See Concierge for example. Replaces NamedTuple definition with instance having
        "<ClassName>/<field>" as values.
        """
        if KEYS := getattr(cls, "KEYS", None):
            values = {
                field: f"{cls.__name__}/{field.lower()}" for field in KEYS._fields
            }
            setattr(cls, "KEYS", KEYS(**values))

    @property
    def mtu(self) -> int:
        if self.state.network and self.state.network.mtu:
            return self.state.network.mtu
        return DEFAULT_MTU

    @property
    def other_routers(self) -> list[Router]:
        return [
            router for router in self.state.routers if router.id != self.context.self_id
        ]

    @property
    def local_router(self) -> Router:
        return self.state.routersById[self.context.self_id]

    @property
    def local_teams(self) -> list[Team]:
        if team_ids := self.local_router.teams:
            return [self.state.teamsById[team_id] for team_id in team_ids]
        else:
            return []

    @property
    def local_net_entities(self) -> list[NetEntity]:
        if net_entities := self.local_router.net_entities:
            return [self.state.netEntitiesById[entity_id] for entity_id in net_entities]
        else:
            return []

    @property
    def local_team_ids(self) -> set[TeamId]:
        return {team.id for team in self.local_teams}

    @property
    def local_net_entity_ids(self) -> set[NetEntityId]:
        return {ent.id for ent in self.local_net_entities}

    @property
    def _loop(self):
        return asyncio.get_running_loop()

    async def _yield_all_updates(self) -> AsyncGenerator[InternalUpdate]:
        """
        Yield all updates from self.updates until queue is shut down.

        Implemented here for convenience. Call this method after performing setup in
        the run() method of controllers in order to make it yield all updates from its
        queue and keep your controller alive until the queue is explicitly shut down.
        """
        while True:
            try:
                yield await self.updates.get()
                self.updates.task_done()
            except QueueShutDown:
                break

    @abstractmethod
    async def run(self) -> AsyncGenerator[InternalUpdate, None]:
        """Perform initial setup and return a generator yielding UpdateEvents."""

    async def entity_update(self, entity: Router | Team | Gate, delete: bool = False):
        """Handle an update to any entity."""
        if isinstance(entity, Team):
            await self.team_update(entity, delete)
        elif isinstance(entity, Router):
            await self.router_update(entity, delete)
        elif isinstance(entity, RawGate) or isinstance(entity, ConnGate):
            await self.gate_update(entity, delete)
        else:
            assert_never(entity)

    async def router_update(self, router: Router, delete: bool = False):
        """
        Handle an update to a router.

        Remove resources related to it if delete is true.
        """

    async def team_update(self, team: Team, delete: bool = False):
        """
        Handle an update to a team.

        Remove resources related to it if delete is true.
        """

    async def gate_update(self, gate: Gate, delete: bool = False):
        """
        Handle an update to a Gate.

        Remove resources related to it if delete is true.
        """
