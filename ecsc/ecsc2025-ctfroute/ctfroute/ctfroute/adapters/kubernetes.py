import os
from asyncio import create_task, sleep
from logging import getLogger
from typing import AsyncGenerator, assert_never, cast

import ctfroute_k8s.models.v1 as k8s
import httpx
from cloudcoil.client import Config
from cloudcoil.errors import WatchError
from ctfroute_k8s.watch import watch

from ctfroute.adapters.base import Adapter, AnyExternalUpdate, ExternalUpdate
from ctfroute.adapters.yaml_conf import KubernetesAdapterConfig
from ctfroute.exceptions import CtfRouteException
from ctfroute.state import LocalContext, external
from ctfroute.state.external import GateType
from ctfroute.utils import Backoff, EntityType

LOGGER = getLogger(__name__)


class KubernetesAdapter(Adapter):
    def __init__(
        self,
        initial_state: external.CtfRouteState,
        context: LocalContext,
        config: KubernetesAdapterConfig,
        *args,
        **kwargs,
    ):
        super().__init__(initial_state, context, *args, **kwargs)

        self.c_config = Config()
        if host := os.environ.get("KUBERNETES_SERVICE_HOST"):
            port = os.environ.get("KUBERNETES_SERVICE_PORT", 6443)
            self.c_config = Config(server=f"https://{host}:{port}")

        self.config = config
        self.resource_version: str | None = None
        self.backoff = Backoff()

    @staticmethod
    def _gate_from_k8s(gate: k8s.Gate) -> external.Gate:
        assert gate.metadata is not None
        assert gate.metadata.name is not None

        # Cloudcoil union typing is very weird...
        spec = gate.spec.root
        data = spec.model_dump(exclude_unset=True)

        if spec.type == GateType.raw:
            return external.RawGate(
                id=gate.metadata.name,
                **data,
            )
        elif spec.type == GateType.connection:
            return external.ConnGate(
                id=gate.metadata.name,
                **data,
            )
        else:
            raise ValueError(f"Unknown GateType {spec.type} retrieved from k8s.")

    async def watch(self):
        with self.c_config:
            async for event_type, resource in watch(
                k8s.Gate,
                namespace=self.config.namespace,
                resource_version=self.resource_version,
            ):
                LOGGER.debug(f"{event_type} in gates watch stream")
                match event_type:
                    case "DELETED":
                        assert resource.metadata is not None
                        assert resource.metadata.name is not None
                        resource_id = resource.metadata.name
                        resource = cast(k8s.Gate, resource)
                        if resource_id not in self.current_state.gatesById:
                            LOGGER.warning(
                                f"K8s delete event for unknown gate '{resource_id}',"
                                " propagating delete update anyway"
                            )
                        gate = self._gate_from_k8s(resource)
                        self.current_state.delete(gate)
                        self.updates.put_nowait(
                            ExternalUpdate(
                                entity=gate,
                                delete=True,
                            )
                        )
                    case "ADDED" | "MODIFIED":
                        assert resource.metadata is not None
                        assert resource.metadata.name is not None
                        resource_id = resource.metadata.name
                        resource = cast(k8s.Gate, resource)
                        gate = self._gate_from_k8s(resource)
                        known = self.current_state.gatesById.get(resource_id, None)
                        if known != gate:
                            event = ExternalUpdate(entity=gate)
                            self.handle_update(event)
                            self.updates.put_nowait(event)
                        else:
                            LOGGER.info(
                                f"{event_type} for {resource_id=} received,"
                                " no difference to local state detected"
                            )
                    case "BOOKMARK":
                        assert resource.metadata is not None
                        self.resource_version = resource.metadata.resource_version
                    case "ERROR":
                        raise WatchError(f"Error in watch stream: {resource}")
                    case _ as _unreachable:
                        assert_never(_unreachable)

    async def list_and_watch_indefinitely(self) -> None:
        with self.c_config:
            while True:
                try:
                    if not self.resource_version:
                        k8s_gates = k8s.Gate.list(namespace=self.config.namespace)
                        all_gates = [self._gate_from_k8s(g) for g in k8s_gates]
                        LOGGER.debug(f"Listing returned {len(all_gates)} gates")
                        diff = self.calculate_entity_diff(
                            EntityType.Gate, self.current_state.gates, all_gates
                        )
                        for event in diff:
                            self.handle_update(event)
                            self.updates.put_nowait(event)
                        assert k8s_gates.metadata is not None
                        self.resource_version = k8s_gates.metadata.resource_version

                    # Reset the backoff after successfully talking to the api server
                    self.backoff.reset()
                    await self.watch()
                    LOGGER.debug("Watch ended, resuming immediately")
                except (httpx.RequestError, WatchError):
                    LOGGER.exception(f"Error observing k8s, resuming in {self.backoff}")
                    await sleep(next(self.backoff))
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 410:
                        LOGGER.exception("Watch expired, resuming immediately")
                        self.resource_version = None
                    elif e.response.status_code == 404:
                        raise CtfRouteException(
                            "List / Watch in Kubernetes returned 404."
                            " Did you install the ctfroute CRDs?"
                        )
                    else:
                        LOGGER.exception(
                            f"Http error {e.response.status_code} from k8s,"
                            f" resuming in {self.backoff}"
                        )
                        await sleep(next(self.backoff))

    async def run(
        self,
    ) -> AsyncGenerator[AnyExternalUpdate, None]:
        create_task(self.list_and_watch_indefinitely())
        return self._yield_all_updates()
