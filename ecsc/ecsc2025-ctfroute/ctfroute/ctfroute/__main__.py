import os
import socket
from argparse import ArgumentParser, Namespace
from asyncio import new_event_loop, set_event_loop
from logging import getLogger
from logging.config import dictConfig
from pathlib import Path
from typing import AsyncGenerator, Type, assert_never

from aiostream.stream import merge

from ctfroute.adapters import HttpAdapter, KubernetesAdapter
from ctfroute.adapters.base import Adapter, AnyExternalUpdate, ExternalUpdate
from ctfroute.adapters.yaml_conf import YamlConfig, read_yaml_conf
from ctfroute.controllers import (
    Cleaner,
    Concierge,
    Controller,
    GateKeeper,
    Metrologist,
    PaceKeeper,
    WayFinder,
)
from ctfroute.controllers.base import InternalUpdate
from ctfroute.debug import add_debug_flags, setup_debugging
from ctfroute.state import LocalContext, external, internal
from ctfroute.state.internal import to_internal
from ctfroute.utils import EntityType, setup_logging

LOGGER = getLogger("ctfroute")

CONTROLLERS: list[Type[Controller]] = [
    Metrologist,
    Concierge,
    WayFinder,
    Cleaner,
    GateKeeper,
    PaceKeeper,
]

ROUTER_ID_VAR = "CTF_ROUTE_RID"


def build_context(config: YamlConfig) -> LocalContext:
    self_id: external.RouterId | None = None
    if ROUTER_ID_VAR in os.environ:
        self_id = os.environ[ROUTER_ID_VAR]
    elif config.instance and config.instance.router_id:
        self_id = config.instance.router_id
    else:
        hostname = socket.gethostname()
        for router in config.initial_state.routers:
            if router.host == hostname:
                self_id = router.id
                break

    if self_id is None:
        raise ValueError("Could not determine own router id")

    metrics_enabled = False
    metrics_file: None | Path = None

    if config.instance and (metrics := config.instance.metrics):
        metrics_enabled = True
        if metrics.exists() and metrics.is_dir():
            metrics_file = metrics / f"router-{self_id}.prom"
        else:
            metrics_file = metrics
            metrics.parent.mkdir(parents=True, exist_ok=True)

    return LocalContext(
        self_id=self_id,
        metrics=metrics_enabled,
        metrics_file=metrics_file,
    )


async def run_controller(
    controller: Controller,
) -> AsyncGenerator[tuple[Controller, InternalUpdate]]:
    """
    Wrapper for controllers run methods.

    Wraps the generator yielded by a controllers run method and yields the controller
    itself together with any update it's run method yields. This is used to easily
    attribute updates to specific controllers despite using aiostream.stream.merge.
    """
    generator = await controller.run()
    async for update in generator:
        yield controller, update


async def run_adapter(
    adapter: Adapter,
) -> AsyncGenerator[tuple[Adapter, AnyExternalUpdate]]:
    """Equivalent wrapper for adapters (see run_controller)."""
    generator = await adapter.run()
    async for update in generator:
        yield adapter, update


async def handle_internal_update(
    main_state: internal.CtfRouteState,
    controllers: list[Controller],
    sender: Controller,
    update: InternalUpdate,
):
    """
    Handle internal update.

    InternalUpdates are emitted by controllers and contain only changes to
    internal_state - in contrast to ExternalUpdates. Since adapters are unaware of
    internal_state, InternalUpdates are only propagated to other Controllers.
    """
    entity: internal.Team | internal.Router | internal.Gate
    match update.entity_type:
        case EntityType.Team:
            entity = main_state.teamsById[update.entity_id]
        case EntityType.Router:
            entity = main_state.routersById[update.entity_id]
        case EntityType.Gate:
            entity = main_state.gatesById[update.entity_id]
        case _:
            assert_never(update.entity_type)

    entity.internal_state.update(update.update)

    for controller in controllers:
        # Don't send updates back to the emitting controller to prevent loops
        if controller is sender:
            continue
        # Controllers may always assume that the entity they get belongs to them
        await controller.entity_update(entity.model_copy(deep=True))


async def handle_external_update(
    main_state: internal.CtfRouteState,
    adapters: list[Adapter],
    controllers: list[Controller],
    sender: Adapter,
    update: ExternalUpdate,
):
    """
    Handle external updates.

    ExternalUpdates are emitted by adapters and contain changes to fields other than
    internal_state - in contrast to InternalUpdates. They are propagated to controllers
    and other adapters so we - opportunistically - can avoid handling changes multiple
    time - of course this can never be categorically ruled out since there is a natural
    "race" between adapters.
    """
    for adapter in adapters:
        # Don't send updates back to the emitting adapter
        if sender == adapter:
            continue
        # Adapters may always assume that the entity they get belongs to them
        adapter.handle_update(update.model_copy(deep=True))

    entity = to_internal(update.entity)
    if update.delete:
        main_state.delete(entity)
    else:
        main_state.upsert(entity)

    for controller in controllers:
        # Controllers may always assume that the entity they get belongs to them
        await controller.entity_update(entity.model_copy(deep=True), update.delete)


async def main(args: Namespace) -> None:
    config = read_yaml_conf(args.file)
    if config.instance and config.instance.logging is not None:
        dictConfig(config.instance.logging)

    context = build_context(config)

    main_state = internal.CtfRouteState.from_initial(config.initial_state)

    # Adapters are created from the static startup configuration
    adapters: list[Adapter] = []
    for adapter_config in config.adapters:
        # Instantiate controllers, state is copied, context is immutable
        match adapter_config.type:
            case "http":
                adapters.append(
                    HttpAdapter(
                        config.initial_state.model_copy(deep=True),
                        context,
                        adapter_config,
                    )
                )
            case "kubernetes":
                adapters.append(
                    KubernetesAdapter(
                        config.initial_state.model_copy(deep=True),
                        context,
                        adapter_config,
                    )
                )
            case _:
                assert_never(adapter_config.type)

    # Instantiate controllers, state is copied, context is immutable
    controllers = [C(main_state.model_copy(deep=True), context) for C in CONTROLLERS]

    # Create a stream of internal and update events
    adapter_streams = [run_adapter(a) for a in adapters]
    controller_streams = [run_controller(c) for c in controllers]
    updates = merge(*controller_streams, *adapter_streams)

    async with updates.stream() as stream:
        async for sender, event in stream:
            LOGGER.debug(f"{sender} sent {event}")
            if isinstance(sender, Controller) and isinstance(event, InternalUpdate):
                await handle_internal_update(main_state, controllers, sender, event)

            elif isinstance(sender, Adapter) and isinstance(event, ExternalUpdate):
                await handle_external_update(
                    main_state, adapters, controllers, sender, event
                )
            else:
                # Adapters have their events, and controllers have another
                # If they ever mix something major must have gone wrong
                raise AssertionError(f"Invalid combination of {sender=}, {event=}")


def cli_main():
    parser = ArgumentParser(description="ctfroute")
    parser.add_argument("file", type=Path)
    add_debug_flags(parser)
    args = parser.parse_args()

    setup_logging()
    loop = new_event_loop()
    set_event_loop(loop)

    setup_debugging(args, loop)

    loop.run_until_complete(main(args))


if __name__ == "__main__":
    cli_main()
