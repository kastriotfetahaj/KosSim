import json
import logging
from typing import AsyncGenerator, Literal, Type, TypeVar

from cloudcoil._context import context
from cloudcoil.client import AsyncAPIClient
from cloudcoil.errors import WatchError
from cloudcoil.resources import (
    Resource,
    Unstructured,
)

T = TypeVar("T", bound=Resource)

logger = logging.getLogger(__name__)

_WATCH_TIMEOUT_SECONDS = 300


def async_client_for(resource: Type[Resource]) -> AsyncAPIClient:
    return context.active_config.client_for(resource, sync=False)


WatchEvent = Literal["ADDED", "MODIFIED", "DELETED"]
BookmarkEvent = Literal["BOOKMARK"]
ErrorEvent = Literal["ERROR"]


async def watch(
    resource: Type[T],
    namespace: str | None = None,
    all_namespaces: bool = False,
    field_selector: str | None = None,
    label_selector: str | None = None,
    resource_version: str | None = None,
) -> AsyncGenerator[
    tuple[WatchEvent, T]
    | tuple[BookmarkEvent, Unstructured]
    | tuple[ErrorEvent, Unstructured],
    None,
]:
    self = async_client_for(resource)
    url, params = self._build_watch_params(
        namespace=namespace,
        all_namespaces=all_namespaces,
        field_selector=field_selector,
        label_selector=label_selector,
        resource_version=resource_version,
    )

    logger.debug(
        "Starting watch: kind=%s namespace=%s resource_version=%s",
        self.kind.gvk().kind,
        namespace,
        resource_version,
    )

    async with self._client.stream(
        "GET", url, params=params, timeout=_WATCH_TIMEOUT_SECONDS + 5
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line:
                continue
            try:
                event = json.loads(line)
                type_ = event["type"]
            except (KeyError, json.decoder.JSONDecodeError) as e:
                raise WatchError("Failed to parse line from watch stream") from e

            if type_ in ("BOOKMARK", "ERROR"):
                obj: Unstructured = Unstructured(**event["object"])
                yield type_, obj
            else:
                yield type_, self.kind.model_validate(event["object"])
