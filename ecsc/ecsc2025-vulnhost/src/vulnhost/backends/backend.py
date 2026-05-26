import logging
from abc import ABC, abstractmethod

import paramiko
import socket
from ..config_format import VMConfig, VMStatus, FileConfig


class VMBackend(ABC):
    def __init__(self, name: str, config: dict) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.name: str = name
        self.config = config

    @abstractmethod
    def get_status(self, vms: list[VMConfig]) -> None: ...

    @abstractmethod
    def create_vm(self, vm: VMConfig) -> VMConfig: ...

    @abstractmethod
    def destroy_vm(self, vm: VMConfig) -> None: ...

    @abstractmethod
    def start_vm(self, vm: VMConfig) -> VMStatus: ...

    @abstractmethod
    def stop_vm(self, vm: VMConfig) -> VMStatus: ...

    def reboot_vm(self, vm: VMConfig) -> bool:
        return False

    def reset_vm(self, vm: VMConfig) -> VMConfig:
        return vm

    def reset_root_password(self, vm: VMConfig) -> bool:
        return False

    @abstractmethod
    def set_sshkeys(self, vm: VMConfig, keys: str) -> None: ...

    @abstractmethod
    def set_root_password(self, vm: VMConfig, password: str) -> None: ...

    @abstractmethod
    def set_files(self, vm: VMConfig, files: dict[str, FileConfig]) -> None: ...

    def transform_backend_options(self, vm: VMConfig, options: dict) -> None:
        pass

    def statistics_start(self) -> None:
        pass

    def get_statistics(self, vm: VMConfig) -> list[dict]:
        return []

    def statistics_finished(self) -> list[dict]:
        return []

    def statistics_is_overloaded(self) -> bool:
        return False

    def run_ssh_command(self, vm: VMConfig, cmd: str) -> tuple[int, bytes, bytes]:
        if vm.ip is None:
            raise ValueError("ip must be set")
        username = self.config.get("ssh_user", "root")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.logger.info(f"     ssh to {vm.ip} ...", extra={"ip": vm.ip, "cmd": cmd})
        try:
            ssh.connect(
                vm.ip,
                22,
                username,
                key_filename=self.config["ssh_private_key"],
                timeout=4,
            )
            _, stdout, stderr = ssh.exec_command(cmd)
            rc = stdout.channel.recv_exit_status()
            return rc, stdout.read(), stderr.read()
        finally:
            ssh.close()
            self.logger.info(f"     ssh to {vm.ip} complete.")

    def server_name(self, vm: VMConfig) -> str:
        name = self.config["server_name"]
        if vm.team is not None:
            name += f"-team{vm.team}"
        return name

    def check_ssh_active(self, ip: str) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(4)
            s.connect((ip, 22))
            s.shutdown(socket.SHUT_RDWR)
            return True
        except:
            return False
        finally:
            s.close()


def get_backend(kind: str, name: str, config: dict) -> VMBackend:
    if kind == "podman":
        from .podman_backend import PodmanBackend

        return PodmanBackend(name, config)
    if kind == "hetzner" or kind == "hcloud":
        from .hetzner_cloud_backend import HetznerCloudBackend

        return HetznerCloudBackend(name, config)
    if kind == "ovhcloud" or kind == "ovh" or kind == "openstack":
        from .openstack_backend import OpenstackBackend

        return OpenstackBackend(name, config)
    raise Exception(f'Backend kind "{kind}" not found.')
