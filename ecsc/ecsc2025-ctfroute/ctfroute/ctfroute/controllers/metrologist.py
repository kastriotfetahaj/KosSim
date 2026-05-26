import asyncio
import logging
from asyncio import create_task

import prometheus_client as prom

from ctfroute.controllers import Controller, GateKeeper
from ctfroute.controllers.wayfinder import WayFinder
from ctfroute.drivers.base import RouterConnection
from ctfroute.state.internal import Gate, Router, Team

LOGGER = logging.getLogger(__name__)

RouterConnectionState = RouterConnection.State

UNKNOWN = "unknown"


class Metrologist(Controller):
    write_interval = 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.registry = prom.CollectorRegistry()
        self.metric_last_written = prom.Gauge(
            "last_written",
            "When metrologist last wrote the metrics.",
            registry=self.registry,
        )
        self.metric_gate_enforced = prom.Enum(
            name="gate_enforced",
            documentation="True if the gate is enforced, False otherwise.",
            states=["True", "False", UNKNOWN],
            labelnames=["gate"],
            registry=self.registry,
        )
        self.metric_router_connection = prom.Enum(
            name="router_connection",
            documentation="State of connections to other routers.",
            states=[str(s) for s in RouterConnectionState] + [UNKNOWN],
            labelnames=["other_router"],
            registry=self.registry,
        )

    def _write_metrics(self):
        assert self.context.metrics_file is not None
        self.metric_last_written.set_to_current_time()
        prom.write_to_textfile(str(self.context.metrics_file), self.registry)

    async def _run(self):
        while True:
            self._write_metrics()
            await asyncio.sleep(self.write_interval)

    async def run(self):
        for gate in self.state.gates:
            await self.gate_update(gate)

        for team in self.state.teams:
            await self.team_update(team)

        for router in self.state.routers:
            await self.router_update(router)

        if self.context.metrics:
            create_task(self._run())

        return self._yield_all_updates()

    async def router_update(self, router: Router, delete: bool = False):
        """Handle an update to a router."""
        state = router.internal_state.get(WayFinder.KEYS.STATE, "unknown")

        LOGGER.debug(f"Router update: {router.id} {delete=} {state=}")
        self.metric_router_connection.labels(other_router=router.id).state(str(state))
        self.state.routersById[router.id] = router

    async def team_update(self, team: Team, delete: bool = False):
        """Handle an update to a team."""

    async def gate_update(self, gate: Gate, delete: bool = False):
        """Handle an update to a Gate."""
        enforced = gate.internal_state.get(GateKeeper.KEYS.ENFORCED, "unknown")
        LOGGER.debug(f"Gate update: {gate.id=} {delete=} {enforced=}")
        self.metric_gate_enforced.labels(gate=gate.id).state(str(enforced))
        self.state.gatesById[gate.id] = gate
