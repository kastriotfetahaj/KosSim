import json
import os
from collections import defaultdict
from typing import Any
from enum import Enum

import marshmallow_dataclass
from dataclasses import dataclass, field


class VMStatus(Enum):
    UNKNOWN = 0
    MISSING = 1
    STOPPED = 2
    RUNNING = 3
    CREATING = 4
    BOOTING = 5
    BUSY = 6


@dataclass
class FileConfig:
    content: str = field()
    permission: str | None = field(default=None)
    owner: str | None = field(default=None)

    def clone(self) -> "FileConfig":
        return FileConfig(
            content=self.content, permission=self.permission, owner=self.owner
        )


@dataclass
class VMConfig:
    status: VMStatus = field(default=VMStatus.UNKNOWN)
    team: int | None = field(default=None)
    kind: str = field(default="")
    sshkey: str | None = field(default=None)
    files: dict[str, FileConfig] = field(default_factory=dict)
    root_password: str | None = field(default=None)
    ip: str | None = field(default=None)
    action_counters: dict[str, int] = field(
        default_factory=lambda: defaultdict(lambda: 0)
    )
    backend_options: dict[str, Any] = field(default_factory=dict)

    def clone(self) -> "VMConfig":
        return VMConfig(VMConfigSchema().dump(self))

    def clone_minimal(self) -> "VMConfig":
        return VMConfig(team=self.team, kind=self.kind)

    def str_minimal(self) -> str:
        s = f"VM {self.kind}/team{self.team}: {self.status.name}"
        if self.sshkey:
            s += ", sshkey"
        if self.root_password:
            s += f', root password="{self.root_password}"'
        if self.files:
            s += (
                f", {len(self.files)} files ("
                + ", ".join(os.path.basename(fname) for fname in self.files.keys())
                + ")"
            )
        return s


@dataclass
class StatusConfig:
    vms: list[VMConfig] = field()

    def dump(self, **kwargs: Any) -> str:
        return StatusConfigSchema().dumps(self, **kwargs)

    def get_matching_vm(self, vm: VMConfig) -> VMConfig | None:
        for vm2 in self.vms:
            if vm2.team == vm.team and vm2.kind == vm.kind:
                return vm2
        return None


StatusConfigSchema = marshmallow_dataclass.class_schema(StatusConfig)
VMConfigSchema = marshmallow_dataclass.class_schema(VMConfig)


def load_config(data: str) -> StatusConfig:
    return StatusConfigSchema().load(json.loads(data))
