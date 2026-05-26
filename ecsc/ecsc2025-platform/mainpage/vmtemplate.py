from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any

import dateutil.parser
from constance import config


@dataclass
class VmTemplate:
    name: str
    description: str
    template: dict[str, Any]
    ip_suffix: int = 2
    control_available_from: datetime | None = None
    control_available_to: datetime | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "VmTemplate":
        d = {f.name: d[f.name] for f in fields(cls) if f.name in d}
        if "control_available_from" in d:
            d["control_available_from"] = dateutil.parser.parse(
                d["control_available_from"]
            ).astimezone(timezone.utc)
        if "control_available_to" in d:
            d["control_available_to"] = dateutil.parser.parse(
                d["control_available_to"]
            ).astimezone(timezone.utc)
        return cls(**d)

    @property
    def constance_setting_start(self) -> str:
        return f"VM control {self.name} begin"

    @property
    def constance_setting_end(self) -> str:
        return f"VM control {self.name} end"

    @property
    def runtime_control_available_from(self) -> datetime:
        if self.control_available_from is not None:
            return self.control_available_from
        return getattr(config, self.constance_setting_start).astimezone(timezone.utc)

    @property
    def runtime_control_available_to(self) -> datetime:
        if self.control_available_to is not None:
            return self.control_available_to
        return getattr(config, self.constance_setting_end).astimezone(timezone.utc)

    @property
    def has_control_available_from(self) -> bool:
        return self.runtime_control_available_from.year > 2001

    @property
    def has_control_available_to(self) -> bool:
        return self.runtime_control_available_to.year < 2099

    @property
    def control_available(self) -> bool:
        return (
            self.runtime_control_available_from
            <= datetime.now(tz=timezone.utc)
            < self.runtime_control_available_to
        )
