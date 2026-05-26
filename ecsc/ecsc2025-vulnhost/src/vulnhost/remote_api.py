import logging
import time
from typing import Any

import requests

from .config_format import StatusConfig, load_config
from .manager import VulnhostManager


class RemoteApi:
    def __init__(self, manager: VulnhostManager) -> None:
        self.manager = manager
        self._session = requests.Session()
        self._logger = logging.getLogger(self.__class__.__name__)

    def request(self, method: str, endpoint: str, **kwargs: Any) -> requests.Response:
        if "timeout" not in kwargs:
            kwargs["timeout"] = 10
        ts = time.monotonic()
        self._logger.debug(f"{method} {endpoint} ...")
        response = self._session.request(method, endpoint, **kwargs)
        dt = time.monotonic() - ts
        self._logger.debug(
            f"{method} {endpoint} completed in {dt:.1f}s (status {response.status_code})"
        )
        if dt > 3:
            self._logger.warning(
                f"{method} {endpoint} ({response.status_code}) took {dt:.1f} seconds"
            )
        if response.status_code != 200:
            self._logger.warning(
                f"{method} {endpoint} failed with status code {response.status_code}",
                extra={"body": response.text},
            )
        return response

    def get_remote_config(self) -> StatusConfig | None:
        if self.manager.config_url is None:
            print("No config URL configured")
            return None
        backends = ",".join(name for name in self.manager.backends)
        response = self.request(
            "GET", self.manager.config_url, params={"backends": backends}
        )
        if response.status_code == 200:
            return load_config(response.text)
        else:
            return None

    def set_remote_status(self, status: str) -> None:
        if self.manager.status_url is None:
            print("No status URL configured")
            return None
        self.request(
            "POST",
            self.manager.status_url,
            data=status,
            headers={"Content-type": "application/json; charset=utf-8"},
            timeout=30,
        )

    def send_statistics(self, statistics: list[dict]) -> None:
        if len(statistics) == 0 or self.manager.statistics_url is None:
            return
        self.request("POST", self.manager.statistics_url, json=statistics)
