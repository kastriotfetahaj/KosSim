from functools import partial
from logging import getLogger
from typing import NamedTuple

from ctfroute.controllers.base import Controller, InternalUpdate
from ctfroute.drivers.exceptions import BadState
from ctfroute.drivers.netfilter.driver import GateHandle, NftablesDriver, NFTError
from ctfroute.state.external import GateId, NetEntityId, TeamId
from ctfroute.state.internal import Gate, Team
from ctfroute.state.utils import AreEqual, are_equal
from ctfroute.utils import EntityType

LOGGER = getLogger(__name__)


class GateKeeper(Controller):
    """It's a gatekeeper. It keeps (network) gates."""

    class KEYS(NamedTuple):
        ENFORCED: str
        ERROR_CODE: str
        ERROR_MESSAGE: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.driver: NftablesDriver = NftablesDriver()
        self.current_nft_rules: str | None = None

        self.gate_handles: dict[GateId, GateHandle] = {}

        # Gates that can't be enforced (yet) and should be re-tried if entities were
        # successfully created
        self.gates_to_retry: set[GateId] = set()

        # Net entities that did not have enough state to set up their sets
        self.incomplete_teams: set[TeamId] = set()
        self.incomplete_entities: set[NetEntityId] = set()

    equal_teams: AreEqual[Team] = staticmethod(
        partial(
            are_equal,
            fields=("id", "network", "gateway", "vulnbox"),
        )
    )

    equal_gates: AreEqual[Gate] = staticmethod(
        partial(
            are_equal,
            fields=(
                "id",
                "type",
                "conn_src",
                "conn_dst",
                "expression",
                "period",
                "raw",
            ),
        )
    )

    def try_set_gate(self, gate: Gate) -> None:
        """
        Set gate, update its internal state and emit event.

        Updates the internal state of the gate but does not modify self.state!
        """
        self.gates_to_retry -= {gate.id}
        old_handle = self.gate_handles.get(gate.id, None)

        try:
            self.gate_handles[gate.id] = self.driver.set_gate(gate, old_handle)
            update = {
                self.KEYS.ENFORCED: str(True),
                self.KEYS.ERROR_CODE: None,
                self.KEYS.ERROR_MESSAGE: None,
            }
        except (NFTError, BadState) as e:
            LOGGER.error(f"Failed to deploy gate {gate.id}:\n{e}")

            # Ensure to remove "old version" of gate
            # This should be safe since delete_gate and set_gate are atomic
            if old_handle:
                self.driver.delete_gate(old_handle)
                del self.gate_handles[gate.id]

            update = {
                self.KEYS.ENFORCED: str(False),
                self.KEYS.ERROR_MESSAGE: str(e.msg),
            }
            # This might happen because e.g. a set required for the gate's rules was
            # not created yet, such gates will be reattempted when new entities are
            # created
            if isinstance(e, NFTError):
                update[self.KEYS.ERROR_CODE] = str(e.code)
                self.gates_to_retry.add(gate.id)

        # Update state
        gate.internal_state.update(update)

        # Emit event
        self.updates.put_nowait(
            InternalUpdate(
                entity_type=EntityType.Gate, entity_id=gate.id, update=update
            )
        )

    def _setup(self):
        self.driver.setup()
        # Driver setup flushes the gates chain, so existing handles are now worthless.
        # This should not happen under normal circumstances, but doing it here is
        # useful for tests
        self.gate_handles = {}

        if self.state.network and self.state.network.entities:
            for ent in self.state.network.entities:
                self.driver.set_entity(ent)

        for team in self.state.teams:
            self.driver.set_entity(team)
        try:
            if self.state.network and (nft := self.state.network.nft):
                self.driver.cmd(nft)
                self.current_nft_rules = nft
        except NFTError as e:
            LOGGER.error(f"Failed to deploy network.nft:\n{e}")

        for gate in self.state.gates:
            self.try_set_gate(gate)

    async def run(self):
        self._setup()
        return self._yield_all_updates()

    async def team_update(self, team: Team, delete: bool = False):
        if team.id in self.state.teamsById and not delete:
            current_state = self.state.teamsById[team.id]
            if self.equal_teams(current_state, team):
                # All good, nothing left to do here
                return

        elif team.id in self.incomplete_teams and not delete:
            self.state.upsert(team)
            self.state.teamsById[team.id] = team
            # await self._try_set_up_team(team)
            return

        # TODO Must reattempt self.gates_to_retry if a team update was performed
        # TODO, Needed because a teams network / gateway / vulnbox might change
        raise NotImplementedError(
            f"{type(self).__name__} does not support external team updates yet."
        )

    async def gate_update(self, gate: Gate, delete: bool = False):
        """
        Handle an update to a Gate.

        Remove resources related to it if delete is true.
        """
        if delete:
            if handle := self.gate_handles.get(gate.id, None):
                LOGGER.info(f"Deleting gate '{gate.id}'")
                self.driver.delete_gate(handle)
                del self.gate_handles[gate.id]
            else:
                LOGGER.warning(f"Deleting gate '{gate.id}' - it doesn't have a handle!")

            # Purge from state
            self.state.delete(gate)
            self.gates_to_retry -= {gate.id}

        else:
            old_gate = self.state.gatesById.get(gate.id, None)

            upsert_needed = old_gate is None

            if old_gate is None:
                LOGGER.info(f"Adding gate '{gate.id}': {gate}")
            else:
                # Merge internal states
                gate.internal_state.update(
                    {
                        **old_gate.internal_state,
                        **gate.internal_state,
                    }
                )

                if upsert_needed := not self.equal_gates(old_gate, gate):
                    LOGGER.info(f"Updating gate '{gate.id}': {old_gate} -> {gate}")

            if upsert_needed:
                self.try_set_gate(gate)
            else:
                # Only update internal state
                old_gate.internal_state.update(gate.internal_state)
                LOGGER.debug(f"Gate '{gate.id}' doesn't need an update.")

            self.state.upsert(gate)
