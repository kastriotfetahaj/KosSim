import base64
from typing import Any

import yaml
from passlib.hash import sha512_crypt
import openstack
from openstack.compute.v2.server import Server
from openstack.exceptions import ConflictException

from .backend import VMBackend
from .util import *
from ..config_format import VMConfig, VMStatus, FileConfig

TAG_VULNHOST_MANAGED = "VULNHOST_MANAGED"


def get_ext_net_ipv4(server: Server) -> str | None:
    external_interface = server.addresses.get("Ext-Net")
    if external_interface is None:
        return None

    for address in external_interface:
        if address["version"] == 4:
            return address["addr"]

    return None


class OpenstackBackend(VMBackend):
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        # self.config_file = config.get("config_file", "ovh.conf")
        # self.project = config["project_name"]
        self.client = openstack.connect()
        self.server_cache: dict[str, Server] = {}

        self.keypair = self.client.compute.find_keypair("dummy-key")
        self.image_id = self.config["image_id"]
        self.flavor_id = self.client.compute.find_flavor(self.config["flavor_name"]).id
        self.network_id = self.client.network.find_network("Ext-Net").id

    def _get_server(self, vm: VMConfig, force_update_cache=False) -> Server | None:
        name = self.server_name(vm)
        if name in self.server_cache and not force_update_cache:
            return self.server_cache[name]
        server = self.client.compute.find_server(name, ignore_missing=True)
        if server is not None:
            self.server_cache[name] = server
        return server

    def status_to_vmstatus(self, status: str | None) -> VMStatus:
        # if status == 'initializing': return VMStatus.CREATING
        # if status == 'starting': return VMStatus.BOOTING
        # if status == 'running': return VMStatus.RUNNING
        # if status == 'stopping': return VMStatus.BUSY
        # if status == 'off': return VMStatus.STOPPED
        # if status == 'deleting': return VMStatus.BUSY
        # if status == 'rebuilding': return VMStatus.BUSY
        # if status == 'migrating': return VMStatus.BUSY
        # return VMStatus.UNKNOWN

        if status == "ACTIVE":
            return VMStatus.RUNNING  # The server is active.
        if status == "BUILD":
            return (
                VMStatus.BOOTING
            )  # The server has not finished the original build process.
        if status == "DELETED":
            return VMStatus.UNKNOWN  # The server is permanently deleted.
        if status == "ERROR":
            return VMStatus.UNKNOWN  # The server is in error.
        if status == "HARD_REBOOT":
            return VMStatus.BUSY  # The server is hard rebooting. This is equivalent to pulling the power plug on a physical server, plugging it back in, and rebooting it.
        if status == "MIGRATING":
            return VMStatus.BUSY  # The server is being migrated to a new host.
        if status == "PASSWORD":
            return VMStatus.BUSY  # The password is being reset on the server.
        if status == "PAUSED":
            return VMStatus.STOPPED  # In a paused state, the state of the server is stored in RAM. A paused server continues to run in frozen state.
        if status == "REBOOT":
            return VMStatus.BUSY  # The server is in a soft reboot state. A reboot command was passed to the operating system.
        if status == "REBUILD":
            return VMStatus.BUSY  # The server is currently being rebuilt from an image.
        if status == "RESCUE":
            return VMStatus.UNKNOWN  # The server is in rescue mode. A rescue image is running with the original server image attached.
        if status == "RESIZE":
            return VMStatus.BUSY  # Server is performing the differential copy of data that changed during its initial copy. Server is down for this stage.
        if status == "REVERT_RESIZE":
            return VMStatus.BUSY  # The resize or migration of a server failed for some reason. The destination server is being cleaned up and the original source server is restarting.
        if status == "SHELVED":
            return VMStatus.BUSY  # The server is in shelved state. Depending on the shelve offload time, the server will be automatically shelved offloaded.
        if status == "SHELVED_OFFLOADED":
            return VMStatus.BUSY  # The shelved server is offloaded (removed from the compute host) and it needs unshelved action to be used again.
        if status == "SHUTOFF":
            return (
                VMStatus.STOPPED
            )  # The server is powered off and the disk image still persists.
        if status == "SOFT_DELETED":
            return VMStatus.UNKNOWN  # The server is marked as deleted but the disk images are still available to restore.
        if status == "SUSPENDED":
            return VMStatus.STOPPED  # The server is suspended, either by request or necessity. When you suspend a server, its state is stored on disk, all memory is written to disk, and the server is stopped. Suspending a server is similar to placing a device in hibernation and its occupied resource will not be freed but rather kept for when the server is resumed. If a server is infrequently used and the occupied resource needs to be freed to create other servers, it should be shelved.
        if status == "UNKNOWN":
            return (
                VMStatus.UNKNOWN
            )  # The state of the server is unknown. Contact your cloud provider.
        if status == "VERIFY_RESIZE":
            return VMStatus.BUSY  # System is awaiting confirmation that the server is operational after a move or resize.
        return VMStatus.UNKNOWN

    def get_status(self, vms: list[VMConfig]) -> None:
        self.logger.info("[TRACE] OpenstackBackend.get_status")
        self.server_cache = {
            server.name: server
            for server in self.client.compute.servers(tags=[TAG_VULNHOST_MANAGED])
        }

        vm_names = {self.server_name(vm): vm.status for vm in vms}
        sever_cache_keys = {
            key: value.status for key, value in self.server_cache.items()
        }

        self.logger.debug(f"vms (pre): {vm_names}")
        self.logger.debug(f"server_cache: {sever_cache_keys}")
        for vm in vms:
            name = self.server_name(vm)
            if name not in self.server_cache:
                vm.status = VMStatus.MISSING
            else:
                cached = self.server_cache[name]
                vm.status = self.status_to_vmstatus(cached.status)
                vm.backend_options["openstack_status"] = cached.status
                access_ip = get_ext_net_ipv4(cached)
                if access_ip is not None:
                    vm.ip = access_ip
                    vm.backend_options["ssh_active"] = self.check_ssh_active(access_ip)
                # if cached.server_type is not None:
                #     vm.backend_options['server_type'] = cached.server_type.name
                # self.check_blocking_actions(vm)

        vm_names = {self.server_name(vm): vm.status for vm in vms}
        self.logger.debug(f"vms (post): {vm_names}")

    def create_vm(self, vm: VMConfig) -> VMConfig:
        self.logger.debug(f"[TARGET_VM] {vm}")
        vm2 = vm.clone_minimal()
        admin_password = vm.root_password or generate_pw()
        admin_hash = sha512_crypt.hash(admin_password)
        self.logger.debug(f"{admin_hash=}")
        # cloudinit: dict[str, Any] = {'runcmd': [
        #     "sed '/^root/s/:0:0:99999:/:1:0:99999:/' -i /etc/shadow"]}  # initial command to remove "root user password reset" problem
        cloudinit: dict[str, Any] = {
            "runcmd": ["systemctl enable --now wg-quick@game"],
            "ssh_pwauth": True,
            "package_update": False,
            "package_upgrade": False,
            # "password": admin_hash,
            "chpasswd": {
                "expire": False,
                "users": [
                    {"name": "root", "password": admin_hash, "type": "hash"},
                    {"name": "ubuntu", "password": admin_hash, "type": "hash"},
                ],
            },
        }

        for fname, fc in vm.files.items():
            entry = {
                "path": fname,
                "encoding": "b64",
                "content": base64.b64encode(fc.content.encode()).decode(),
            }
            if fc.owner:
                entry["owner"] = fc.owner
            if fc.permission:
                entry["permissions"] = fc.permission
            if "write_files" not in cloudinit:
                cloudinit["write_files"] = []
            cloudinit["write_files"].append(entry)
            vm2.files[fname] = fc.clone()
        if vm.sshkey:
            cloudinit["ssh_authorized_keys"] = vm.sshkey.split("\n")
            vm2.sshkey = vm.sshkey
        vm2.status = VMStatus.CREATING
        for k, v in vm.action_counters.items():
            vm2.action_counters[k] = v
        cloudinit_str = "#cloud-config\n" + yaml.dump(cloudinit)

        server: Server = self.client.compute.create_server(
            name=self.server_name(vm2),
            image_id=self.image_id,
            flavor_id=self.flavor_id,
            networks=[{"uuid": self.network_id}],
            keypair=self.keypair.name,
            admin_password=admin_password,  # NEEDS TO BE SET IN CLOUD INIT
            tags=[TAG_VULNHOST_MANAGED],
            user_data=base64.b64encode(cloudinit_str.encode()).decode(),
        )

        self.server_cache[self.server_name(vm2)] = server
        # vm2.ip = get_ext_net_ipv4(server)
        vm2.root_password = admin_password

        return vm2

    def destroy_vm(self, vm: VMConfig) -> None:
        if (server := self._get_server(vm)) is not None:
            self.client.compute.delete_server(
                server, ignore_missing=True
            )  # TODO: force?

    def start_vm(self, vm: VMConfig) -> VMStatus:
        server = self._get_server(vm)
        if server and self.status_to_vmstatus(server.status) in (
            VMStatus.UNKNOWN,
            VMStatus.STOPPED,
        ):
            try:
                self.client.compute.start_server(server)
            except ConflictException:
                self.logger.info("Conflict in start_vm")
                server = self._get_server(vm, True)
                assert server is not None

                return self.status_to_vmstatus(server.status)
            return VMStatus.BOOTING
        return vm.status

    def stop_vm(self, vm: VMConfig) -> VMStatus:
        server = self._get_server(vm)
        if server and self.status_to_vmstatus(server.status) in (VMStatus.RUNNING,):
            try:
                self.client.compute.stop_server(server)
            except ConflictException:
                self.logger.info("Conflict in stop_vm")
                server = self._get_server(vm, True)
                assert server is not None

                return self.status_to_vmstatus(server.status)
            return VMStatus.BUSY
        return vm.status

    def reboot_vm(self, vm: VMConfig) -> bool:
        server = self._get_server(vm)
        if server and self.status_to_vmstatus(server.status) in (VMStatus.RUNNING,):
            self.client.compute.reboot_server(server, "HARD")
            return True
        return False

    def reset_vm(self, vm: VMConfig) -> VMConfig:
        server = self._get_server(vm)
        if server:
            # images = [image for image in self.client.images.get_all() if
            #           image.name == self.config['image_name'] or image.description == self.config['image_name']]
            # if len(images) == 0: raise Exception('Image not found')
            # if len(images) > 1: raise Exception('Image description not unique')
            # TODO: Do we need extra args here?
            new_server: Server = self.client.compute.rebuild_server(
                server, self.image_id
            )
            self.server_cache[server.name] = new_server

            # self.running_actions[self.server_name(vm)].append(response)
            vm.status = self.status_to_vmstatus(new_server.status)
        return vm

    def reset_root_password(self, vm: VMConfig) -> bool:
        self.logger.error("[Err] PW Reset unsupported")
        return False
        # server = self._get_server(vm)
        # if server and self.status_to_vmstatus(server.status) in (
        #     VMStatus.RUNNING,
        #     VMStatus.STOPPED,
        # ):
        #     new_password = generate_pw()
        #     self.set_root_password(vm, new_password)
        #     vm.root_password = new_password
        #     return True
        # return False

    def set_sshkeys(self, vm: VMConfig, keys: str) -> None:
        self.logger.error("[Err] Setting SSHKeys after creation is unsupported")

    # @abstractmethod
    def set_root_password(self, vm: VMConfig, password: str) -> None:
        return
        # server = self._get_server(vm)
        # if server and self.status_to_vmstatus(server.status) in (
        #     VMStatus.RUNNING,
        #     VMStatus.STOPPED,
        # ):
        #     self.client.compute.change_server_password(server, password)
        #     self.logger.info(f"[INFO] PW set for server {server.name}")
        #     return
        # self.logger.warning("[WARN] ignored pw set request!")

    def set_files(self, vm: VMConfig, files: dict[str, FileConfig]) -> None:
        self.logger.error("[ERR] Cannot change files after start")

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
