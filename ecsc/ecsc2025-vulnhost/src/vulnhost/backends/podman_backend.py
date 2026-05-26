import base64
import json
import os
import shlex
import subprocess

from .backend import VMBackend
from ..config_format import VMConfig, VMStatus, FileConfig

"""
{
    "backend": "podman",
    "container_name": "",
    "image": "",
    
    "hostname": "",
    "sudo": false,
    "additional_args": []
}
"""


class PodmanBackend(VMBackend):
    ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "podman")

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self.additional_args: list[str] = config.get("additional_args", [])
        self.sudo: bool = config.get("sudo", False)

    def get_status(self, vms: list[VMConfig]) -> None:
        cmd = ["podman", "container", "ls", "-a", "--format=json"]
        if self.sudo:
            cmd = ["sudo"] + cmd
        ps = subprocess.check_output(cmd)
        data = json.loads(ps.decode())
        running_vms = {name: x for x in data for name in x["Names"]}
        for vm in vms:
            cn = self.container_name(vm)
            if cn in running_vms:
                status = running_vms[cn]["Status"]
                if status.startswith("Up "):
                    vm.status = VMStatus.RUNNING
                else:
                    vm.status = VMStatus.STOPPED
            else:
                vm.status = VMStatus.MISSING

    def container_name(self, vm: VMConfig) -> str:
        name = self.config["container_name"]
        if vm.team is not None:
            name += f"_team{vm.team}"
        return name

    def hostname(self, vm: VMConfig) -> str:
        name = self.config.get("hostname", self.name)
        if vm.team is not None:
            name += f"_team{vm.team}"
        return name

    def create_vm(self, vm: VMConfig) -> VMConfig:
        # https://github.com/containers/libpod/blob/master/docs/source/markdown/podman-create.1.md
        cmd = ["podman", "create", "-d"] + self.additional_args
        cmd += [
            "-h",
            self.hostname(vm),
            "--name=" + self.container_name(vm),
            "--restart=always",
        ]
        # mount files
        if vm.files:
            dir = os.path.join(self.ROOT, self.container_name(vm))
            os.makedirs(dir, exist_ok=True)
            for fname, config in vm.files.items():
                real_name = os.path.join(dir, os.path.basename(fname))
                with open(real_name, "w") as f:
                    f.write(config.content)
                cmd += ["-v", f"{real_name}:{fname}"]
        # finish command
        cmd += [self.config["image"]]
        if self.sudo:
            cmd = ["sudo"] + cmd
        # execute
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
        vm2 = vm.clone_minimal()
        vm2.files = {
            fname: FileConfig(content=fc.content) for fname, fc in vm.files.items()
        }
        vm2.status = VMStatus.STOPPED
        for k, v in vm.action_counters.items():
            vm2.action_counters[k] = v
        return vm2

    def destroy_vm(self, vm: VMConfig) -> None:
        cmd = ["podman", "rm", "-f", self.container_name(vm)]
        if self.sudo:
            cmd = ["sudo"] + cmd
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL)

    def start_vm(self, vm: VMConfig) -> VMStatus:
        cmd = ["podman", "start", self.container_name(vm)]
        if self.sudo:
            cmd = ["sudo"] + cmd
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
        return VMStatus.RUNNING

    def stop_vm(self, vm: VMConfig) -> VMStatus:
        cmd = ["podman", "stop", self.container_name(vm)]
        if self.sudo:
            cmd = ["sudo"] + cmd
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
        return VMStatus.STOPPED

    def reboot_vm(self, vm: VMConfig) -> bool:
        cmd = ["podman", "restart", self.container_name(vm)]
        if self.sudo:
            cmd = ["sudo"] + cmd
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
        return True

    def reset_vm(self, vm: VMConfig) -> VMConfig:
        self.destroy_vm(vm)
        return self.create_vm(vm)

    def reset_root_password(self, vm: VMConfig) -> bool:
        passwd = base64.urlsafe_b64encode(os.urandom(15)).decode()
        self.set_root_password(vm, passwd)
        return vm.status == VMStatus.RUNNING

    def set_sshkeys(self, vm: VMConfig, keys: str) -> None:
        # TODO for now it's an "add ssh key"
        if vm.status == VMStatus.RUNNING:
            cmd = ["podman", "exec", self.container_name(vm)]
            cmd += [
                "sh",
                "-c",
                f" echo {shlex.quote(keys)} >> /root/.ssh/authorized_keys",
            ]
            if self.sudo:
                cmd = ["sudo"] + cmd
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
            vm.sshkey = keys
            self.logger.info("[OK] updated ssh keys")

    def set_root_password(self, vm: VMConfig, password: str) -> None:
        if vm.status == VMStatus.RUNNING:
            cmd = ["podman", "exec", self.container_name(vm)]
            cmd += ["sh", "-c", f" echo {shlex.quote('root:' + password)} | chpasswd"]
            if self.sudo:
                cmd = ["sudo"] + cmd
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
            vm.root_password = password
            self.logger.info("[OK] updated root password")

    def set_files(self, vm: VMConfig, files: dict[str, FileConfig]) -> None:
        for fname, config in files.items():
            if fname in vm.files:
                if vm.files[fname].content != config.content:
                    real_name = os.path.join(
                        self.ROOT, self.container_name(vm), os.path.basename(fname)
                    )
                    with open(real_name, "w") as f:
                        f.write(config.content)
                    vm.files[fname].content = config.content
                if (
                    config.permission is not None
                    and vm.files[fname].permission != config.permission
                    and vm.status == VMStatus.RUNNING
                ):
                    try:
                        cmd = ["podman", "exec", self.container_name(vm)]
                        cmd += [
                            "sh",
                            "-c",
                            f" chmod {shlex.quote(config.permission)} {shlex.quote(fname)}",
                        ]
                        if self.sudo:
                            cmd = ["sudo"] + cmd
                        subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
                    except subprocess.CalledProcessError:
                        pass
                    vm.files[fname].permission = config.permission
                if (
                    config.owner is not None
                    and vm.files[fname].owner != config.owner
                    and vm.status == VMStatus.RUNNING
                ):
                    try:
                        cmd = ["podman", "exec", self.container_name(vm)]
                        cmd += [
                            "sh",
                            "-c",
                            f" chown {shlex.quote(config.owner)} {shlex.quote(fname)}",
                        ]
                        if self.sudo:
                            cmd = ["sudo"] + cmd
                        subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
                    except subprocess.CalledProcessError:
                        pass
                    vm.files[fname].owner = config.owner
