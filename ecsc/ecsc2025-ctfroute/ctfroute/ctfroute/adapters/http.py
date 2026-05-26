import asyncio
from asyncio import Event
from logging import getLogger
from typing import AsyncGenerator

import aiohttp
import aiohttp.http_exceptions
import aiohttp.web_exceptions
from pydantic import ValidationError

from ctfroute.adapters.base import (
    Adapter,
    AnyExternalUpdate,
)
from ctfroute.adapters.yaml_conf import HttpAdapterConfig
from ctfroute.state import LocalContext, external
from ctfroute.utils import EntityType

LOGGER = getLogger(__name__)


class HttpAdapter(Adapter):
    task: asyncio.Task | None
    stop_event: Event

    def __init__(
        self,
        initial_state: external.CtfRouteState,
        context: LocalContext,
        config: HttpAdapterConfig,
        *args,
        **kwargs,
    ):
        super().__init__(initial_state, context, *args, **kwargs)

        self.task = None
        # Event to signal a graceful shutdown of this adapter task
        self.stop_event = Event()
        self.config = config
        self._session: aiohttp.ClientSession | None = None

    async def _wait_for_poll(self) -> bool:
        """
        Waits until the next loop iteration, or until a stop has been signalled.

        True if the task should continue.
        """
        try:
            async with asyncio.timeout(float(self.config.poll_interval)):
                await self.stop_event.wait()
                LOGGER.debug("Stop-Event signalled!")
                return False
        except TimeoutError:
            return True

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        elif self._session.closed:
            self._session = aiohttp.ClientSession()

        return self._session

    async def _fetch_update_from_remote(self) -> external.CtfRouteState:
        response = await self.session.get(self.config.url, raise_for_status=True)
        text = await response.text()

        target_state: external.CtfRouteState = (
            external.CtfRouteState.model_validate_json(text)
        )
        return target_state

    def handle_new_state(self, target_state: external.CtfRouteState) -> None:
        upsert_events: list[AnyExternalUpdate] = []

        if EntityType.Router in self.config.entity_types:
            upsert_events += self.calculate_entity_diff(
                EntityType.Router, self.current_state.routers, target_state.routers
            )
        if EntityType.Team in self.config.entity_types:
            upsert_events += self.calculate_entity_diff(
                EntityType.Team, self.current_state.teams, target_state.teams
            )
        if EntityType.Gate in self.config.entity_types:
            upsert_events += self.calculate_entity_diff(
                EntityType.Gate, self.current_state.gates, target_state.gates
            )

        for event in upsert_events:
            LOGGER.debug(f"Emitting {event}")
            self.handle_update(event)
            self.updates.put_nowait(event)

    async def _poll_task_loop(self):
        LOGGER.info("HTTP Adapter poll-task started")
        LOGGER.debug(f"HTTPAdapterConfig: {self.config}")
        while await self._wait_for_poll():
            try:
                new_target_state = await self._fetch_update_from_remote()
            except aiohttp.ClientError as e:
                LOGGER.warning(
                    f"HttpClient error when trying to fetch remote state {e}"
                )
                continue
            except aiohttp.http_exceptions.HttpProcessingError as e:
                LOGGER.warning(
                    f"HttpProcessingError error when trying to fetch remote state {e}"
                )
                continue
            except aiohttp.web_exceptions.HTTPException as e:
                LOGGER.warning(
                    f"HTTP Server error when trying to fetch remote state {e}"
                )
                continue
            except ValidationError as e:
                LOGGER.warning(
                    f"Server Target-State json model failed to be validated! {e}"
                )
                continue

            self.handle_new_state(new_target_state)

    async def _poll_task(self):
        try:
            await self._poll_task_loop()
        except Exception:
            LOGGER.exception("HTTP Poll task encountered a unhandled exception")
            raise

    async def run(
        self,
    ) -> AsyncGenerator[AnyExternalUpdate, None]:
        self.task = asyncio.create_task(self._poll_task())
        return self._yield_all_updates()
