import asyncio
import random
from ipaddress import IPv4Address
from typing import Any, AsyncGenerator, Generator, override

import aiohttp
import pytest

from ctfroute.adapters.base import AnyExternalUpdate, ExternalUpdate
from ctfroute.adapters.http import HttpAdapter, HttpAdapterConfig
from ctfroute.adapters.yaml_conf import YamlConfig
from ctfroute.state import LocalContext, external
from ctfroute.utils import EntityType

POLL_INTERVAL = 0.02


class FakeHttpAdapter(HttpAdapter):
    external_state: str
    connection_error: Exception | None

    def __init__(
        self,
        initial_state: external.CtfRouteState,
        context: LocalContext,
        config: HttpAdapterConfig,
        external_state: str,
        *args,
        **kwargs,
    ):
        super().__init__(initial_state, context, config, *args, **kwargs)
        self.external_state = external_state
        self.connection_error = None

    @override
    async def _fetch_update_from_remote(self) -> external.CtfRouteState:
        if self.connection_error is not None:
            raise self.connection_error

        target_state: external.CtfRouteState = (
            external.CtfRouteState.model_validate_json(self.external_state)
        )
        return target_state

    @property
    def external_state_object(self) -> external.CtfRouteState:
        return external.CtfRouteState.model_validate_json(self.external_state)

    def set_external_state_object(self, external_state_object: external.CtfRouteState):
        self.external_state = external_state_object.model_dump_json()


async def iterate_with_timeout(
    event_stream: AsyncGenerator[AnyExternalUpdate, None],
) -> AsyncGenerator[AnyExternalUpdate | None]:
    """
    Wraps the stream in a timeout yielding None after a few POLL_INTERVALs.

    Shields the underlying AsyncGenerator from the timeout-cancellation,
    so it can be awaited once again without dropping all future events.
    """
    next_result = asyncio.Future()
    try:
        next_result = asyncio.ensure_future(anext(event_stream))
        while True:
            try:
                async with asyncio.timeout(2 * POLL_INTERVAL):
                    # Await the next item in a shielded future.
                    # If the item comes fast enough, it will be retuned
                    # Otherwise it can be retrieved on the next loop iteration
                    yield await asyncio.shield(next_result)
                next_result = asyncio.ensure_future(anext(event_stream))
            except asyncio.TimeoutError:
                yield None

    except StopAsyncIteration:
        pass

    finally:
        next_result.cancel()


@pytest.fixture(scope="function")
def fake_http_adapter(
    integration_ctfroute_conf: YamlConfig,
) -> Generator[FakeHttpAdapter, Any, None]:
    # Dump the initial yaml state into json to have consistent state
    initial_state = integration_ctfroute_conf.initial_state
    external_state = initial_state.model_dump_json()
    local_context = LocalContext(self_id="test_router")

    fake_adapter_config = HttpAdapterConfig(
        type="http",
        poll_interval=POLL_INTERVAL,
        url="https://fakeurl.veryrealtld",
        entity_types=[EntityType.Router, EntityType.Team, EntityType.Gate],
    )

    adapter = FakeHttpAdapter(
        initial_state=initial_state,
        context=local_context,
        config=fake_adapter_config,
        external_state=external_state,
    )
    yield adapter

    adapter.stop_event.set()
    if adapter.task is not None:
        if not adapter.task.done():
            adapter.task.cancel()


@pytest.mark.asyncio
async def test_insert_events(fake_http_adapter: FakeHttpAdapter):
    event_stream = iterate_with_timeout(await fake_http_adapter.run())
    external_state = fake_http_adapter.external_state_object

    # Router
    dummy_router = external_state.routers[0].model_copy(deep=True)
    dummy_router.id = "dummy_router"
    dummy_router.host = "dummy_router"
    external_state.routers.append(dummy_router)
    fake_http_adapter.set_external_state_object(external_state)

    router_event = await anext(event_stream)
    assert router_event == ExternalUpdate(entity=dummy_router)

    # Team
    dummy_team = external_state.teams[0].model_copy(deep=True)
    dummy_team.id = "dummy_team"
    dummy_team.vulnbox = IPv4Address("1.2.3.4")
    dummy_team.meta["name"] = "🐸 rop hoppers 🐸"
    external_state.teams.append(dummy_team)
    fake_http_adapter.set_external_state_object(external_state)

    team_event = await anext(event_stream)
    assert team_event == ExternalUpdate(entity=dummy_team)

    # Gate
    dummy_gate = external_state.gates[0].model_copy(deep=True)
    dummy_gate.id = "dummy_gate"
    dummy_gate.expression = "totally a valid filter expression"
    external_state.gates.append(dummy_gate)
    fake_http_adapter.set_external_state_object(external_state)

    gate_event = await anext(event_stream)
    assert gate_event == ExternalUpdate(entity=dummy_gate)

    assert await anext(event_stream) is None


@pytest.mark.asyncio
async def test_insert_events_masked(fake_http_adapter: FakeHttpAdapter):
    fake_http_adapter.config.entity_types = []
    event_stream = iterate_with_timeout(await fake_http_adapter.run())
    external_state = fake_http_adapter.external_state_object

    # Router
    dummy_router = external_state.routers[0].model_copy(deep=True)
    dummy_router.id = "dummy_router"
    dummy_router.host = "dummy_router"
    external_state.routers.append(dummy_router)
    fake_http_adapter.set_external_state_object(external_state)

    assert await anext(event_stream) is None

    # Team
    dummy_team = external_state.teams[0].model_copy(deep=True)
    dummy_team.id = "dummy_team"
    dummy_team.vulnbox = IPv4Address("1.2.3.4")
    dummy_team.meta["name"] = "🐸 rop hoppers 🐸"
    external_state.teams.append(dummy_team)
    fake_http_adapter.set_external_state_object(external_state)

    assert await anext(event_stream) is None

    # Gate
    dummy_gate = external_state.gates[0].model_copy(deep=True)
    dummy_gate.id = "dummy_gate"
    dummy_gate.expression = "totally a valid filter expression"
    external_state.gates.append(dummy_gate)
    fake_http_adapter.set_external_state_object(external_state)

    assert await anext(event_stream) is None


# Technically this is a server side error...
@pytest.mark.asyncio
async def test_insert_events_duplicate(fake_http_adapter: FakeHttpAdapter, caplog):
    event_stream = iterate_with_timeout(await fake_http_adapter.run())
    external_state = fake_http_adapter.external_state_object

    dummy_router = external_state.routers[0].model_copy(deep=True)
    external_state.routers.append(dummy_router)
    fake_http_adapter.set_external_state_object(external_state)
    assert await anext(event_stream) is None
    assert "target_state.routers contains duplicate IDs" in caplog.text


@pytest.mark.asyncio
async def test_upsert_events(fake_http_adapter: FakeHttpAdapter):
    event_stream = iterate_with_timeout(await fake_http_adapter.run())
    external_state = fake_http_adapter.external_state_object

    # Router
    dummy_router = external_state.routers[0]
    dummy_router.host = "dummy_router"
    fake_http_adapter.set_external_state_object(external_state)

    router_event = await anext(event_stream)
    assert router_event == ExternalUpdate(entity=dummy_router)

    # Team
    dummy_team = external_state.teams[0]
    dummy_team.vulnbox = IPv4Address("1.2.3.4")
    dummy_team.meta["name"] = "🐸 rop hoppers 🐸"
    fake_http_adapter.set_external_state_object(external_state)

    team_event = await anext(event_stream)
    assert team_event == ExternalUpdate(entity=dummy_team)

    # Gate
    dummy_gate = external_state.gates[0]
    dummy_gate.expression = "totally a valid filter expression"
    fake_http_adapter.set_external_state_object(external_state)

    gate_event = await anext(event_stream)
    assert gate_event == ExternalUpdate(entity=dummy_gate)

    assert await anext(event_stream) is None


@pytest.mark.asyncio
async def test_order_invariance(fake_http_adapter: FakeHttpAdapter):
    event_stream = iterate_with_timeout(await fake_http_adapter.run())
    external_state = fake_http_adapter.external_state_object

    for _i in range(4):
        random.shuffle(external_state.routers)
        random.shuffle(external_state.teams)
        random.shuffle(external_state.gates)
        fake_http_adapter.set_external_state_object(external_state)

        # Nothing should ever happen here
        assert await anext(event_stream) is None


@pytest.mark.asyncio
async def test_delete_events(fake_http_adapter: FakeHttpAdapter):
    event_stream = iterate_with_timeout(await fake_http_adapter.run())
    external_state = fake_http_adapter.external_state_object

    # Router
    router_len = len(external_state.routers)
    dropped_router = external_state.routers.pop(random.randint(0, router_len - 1))
    fake_http_adapter.set_external_state_object(external_state)

    router_event = await anext(event_stream)
    assert router_event == ExternalUpdate(entity=dropped_router, delete=True)

    # Team
    team_len = len(external_state.teams)
    dropped_team = external_state.teams.pop(random.randint(0, team_len - 1))
    fake_http_adapter.set_external_state_object(external_state)

    team_event = await anext(event_stream)
    assert team_event == ExternalUpdate(entity=dropped_team, delete=True)
    assert router_event != team_event

    # Gate
    gate_len = len(external_state.gates)
    dropped_gate = external_state.gates.pop(random.randint(0, gate_len - 1))
    fake_http_adapter.set_external_state_object(external_state)

    gate_event = await anext(event_stream)
    assert gate_event == ExternalUpdate(entity=dropped_gate, delete=True)
    assert router_event != gate_event
    assert team_event != gate_event

    # Queue should be empty
    assert await anext(event_stream) is None


TEST_EXCEPTIONS = [
    aiohttp.ClientError(),
    aiohttp.ServerTimeoutError(),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("injected_exception", TEST_EXCEPTIONS)
async def test_event_after_connection_exception(
    fake_http_adapter: FakeHttpAdapter, injected_exception
):
    event_stream = iterate_with_timeout(await fake_http_adapter.run())
    external_state = fake_http_adapter.external_state_object

    assert await anext(event_stream) is None

    fake_http_adapter.connection_error = injected_exception
    await asyncio.sleep(2 * POLL_INTERVAL)
    assert await anext(event_stream) is None

    # Test it works once again once the connection issues are gone
    fake_http_adapter.connection_error = None
    dropped_router = external_state.routers.pop(0)
    fake_http_adapter.set_external_state_object(external_state)

    router_event = await anext(event_stream)
    assert router_event == ExternalUpdate(entity=dropped_router, delete=True)


@pytest.mark.asyncio
async def test_event_after_unhandled_exception(
    fake_http_adapter: FakeHttpAdapter, caplog
):
    event_stream = iterate_with_timeout(await fake_http_adapter.run())
    external_state = fake_http_adapter.external_state_object

    assert await anext(event_stream) is None

    fake_http_adapter.connection_error = Exception()
    await asyncio.sleep(2 * POLL_INTERVAL)
    assert await anext(event_stream) is None

    # The task should be gone!
    fake_http_adapter.connection_error = None
    _dropped_router = external_state.routers.pop(0)
    fake_http_adapter.set_external_state_object(external_state)

    assert await anext(event_stream) is None
    assert "Traceback (most recent call last):" in caplog.text


@pytest.mark.asyncio
async def test_invalid_json(fake_http_adapter: FakeHttpAdapter, caplog):
    event_stream = iterate_with_timeout(await fake_http_adapter.run())
    external_state = fake_http_adapter.external_state_object

    assert await anext(event_stream) is None

    fake_http_adapter.external_state = "Definitely valid JSON!"
    await asyncio.sleep(2 * POLL_INTERVAL)
    assert await anext(event_stream) is None
    assert "Invalid JSON" in caplog.text

    dropped_router = external_state.routers.pop(0)
    fake_http_adapter.set_external_state_object(external_state)

    router_event = await anext(event_stream)
    assert router_event == ExternalUpdate(entity=dropped_router, delete=True)
