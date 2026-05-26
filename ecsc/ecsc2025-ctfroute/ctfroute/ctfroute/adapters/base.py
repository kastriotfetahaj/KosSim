import logging
from abc import ABC, abstractmethod
from asyncio import Queue, QueueShutDown
from typing import AsyncGenerator, Generic, Sequence, TypeVar

from pydantic import BaseModel

from ctfroute.state import LocalContext, external
from ctfroute.utils import EntityType

ExternalEntityT = TypeVar(
    "ExternalEntityT", external.Router, external.Team, external.Gate, contravariant=True
)

LOGGER = logging.getLogger(__name__)


class ExternalUpdate(BaseModel, Generic[ExternalEntityT]):
    entity: ExternalEntityT
    delete: bool = False

    @property
    def entity_type(self) -> EntityType:
        if isinstance(self.entity, external.Router):
            return EntityType.Router
        if isinstance(self.entity, external.Team):
            return EntityType.Team
        if isinstance(self.entity, external.Gate):
            return EntityType.Gate

        raise NotImplementedError(f"Invalid entity type: {type(self.entity)}")

    def __str__(self):
        if self.delete:
            return f"Delete {{{self.entity}}}"
        else:
            return f"Upsert {{{self.entity}}}"

    def __repr__(self):
        return str(self)


AnyExternalUpdate = (
    ExternalUpdate[external.Team]
    | ExternalUpdate[external.Router]
    | ExternalUpdate[external.Gate]
)


class Adapter(ABC):
    def __init__(
        self,
        initial_state: external.CtfRouteState,
        context: LocalContext,
        *args,
        **kwargs,
    ):
        self.current_state = initial_state
        self.context = context
        self.updates: Queue[ExternalUpdate] = Queue()

    def __str__(self):
        return f"{self.__class__.__name__} on {self.context.self_id}"

    def handle_update(self, event: ExternalUpdate):
        if event.delete:
            self.current_state.delete(event.entity)
        else:
            self.current_state.upsert(event.entity)

    @staticmethod
    def _get_duplicate_ids(
        entities: Sequence[ExternalEntityT],
    ) -> Sequence[str]:
        seen = set()
        seen_multiple = set()
        for ent in entities:
            if ent.id in seen:
                seen_multiple.add(ent.id)
            else:
                seen.add(ent.id)
        return list(seen_multiple)

    @classmethod
    def calculate_entity_diff(
        cls,
        entity_type: EntityType,
        current_entity_state: Sequence[ExternalEntityT],
        target_entity_state: Sequence[ExternalEntityT],
    ) -> list[ExternalUpdate[ExternalEntityT]]:
        duplicate_ids = cls._get_duplicate_ids(target_entity_state)
        if duplicate_ids:
            LOGGER.error(
                f"target_state.{entity_type.state_attribute} contains duplicate IDs:"
                f" {duplicate_ids}"
            )
            return []

        upsert_list = []
        current_entity_dict = {entity.id: entity for entity in current_entity_state}

        for target_entity in target_entity_state:
            # Get (and remove) the current entity with the same ID
            current_entity = current_entity_dict.pop(target_entity.id, None)

            # This must be a new entity,
            # emit an upsert event containing the new entity
            if current_entity is None:
                upsert_event = ExternalUpdate(entity=target_entity)
                upsert_list.append(upsert_event)
                continue

            # If there was an old entity only emit an upsert if something changed
            if target_entity != current_entity:
                upsert_event = ExternalUpdate(entity=target_entity)
                upsert_list.append(upsert_event)

        # All targeted entities were handled in the loop above
        # and were already removed from the dictionary.
        # The leftover entities from the old state should be removed.
        for remaining_entity in current_entity_dict.values():
            upsert_list.append(ExternalUpdate(entity=remaining_entity, delete=True))

        return upsert_list

    @abstractmethod
    async def run(self) -> AsyncGenerator[AnyExternalUpdate, None]:
        raise NotImplementedError()

    async def _yield_all_updates(self) -> AsyncGenerator[AnyExternalUpdate, None]:
        """
        Yield all updates from self.updates until queue is shut down.

        Implemented here for convenience. Call this method after setting up your
        poll-loop / listener the run method of your adapter.
        """
        while True:
            try:
                yield await self.updates.get()
                self.updates.task_done()
            except QueueShutDown:
                break
