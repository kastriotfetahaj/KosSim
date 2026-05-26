import base64
import datetime
import shlex
import time
from collections import defaultdict
from typing import Any

import requests
import yaml
from hcloud import Client
from hcloud.actions.client import BoundAction
from hcloud.actions.domain import Action, ActionTimeoutException, ActionFailedException
from hcloud.firewalls.client import BoundFirewall
from hcloud.firewalls.domain import Firewall
from hcloud.locations.domain import Location
from hcloud.server_types.domain import ServerType
from hcloud.servers.client import BoundServer

from .util import check_ssh_active, server_name, run_ssh_command
from .backend import VMBackend
from ..config_format import VMConfig, VMStatus, FileConfig

"""
{
    "backend": "hetzner",
    "token": "<your-cloud-token>",
    "server_name": "vulnbox",
    "server_type": "cx11",
    "image_name": "...",
    
    "location": "fsn1|nbg1|hel1",
    "ssh_private_key": ".../id_rsa",
    "ssh_user": "root"
}
"""


class HetznerCloudBackend(VMBackend):
    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self.token = config["token"]
        self.client: Client = Client(token=self.token, poll_interval=3)
        self.session: requests.Session = requests.Session()
        self.ratelimit_limit: int | None = None
        self.ratelimit_remaining: int | None = None
        self.ratelimit_reset: int | None = None
        self.ratelimit_overloaded = 720
        self.server_cache: dict[str, BoundServer] = {}
        self.last_statistics_query: dict[str, datetime.datetime] = {}
        self.running_actions: dict[str, list[BoundAction]] = defaultdict(list)

    def status_to_vmstatus(self, status: str | None) -> VMStatus:
        if status == "initializing":
            return VMStatus.CREATING
        if status == "starting":
            return VMStatus.BOOTING
        if status == "running":
            return VMStatus.RUNNING
        if status == "stopping":
            return VMStatus.BUSY
        if status == "off":
            return VMStatus.STOPPED
        if status == "deleting":
            return VMStatus.BUSY
        if status == "rebuilding":
            return VMStatus.BUSY
        if status == "migrating":
            return VMStatus.BUSY
        return VMStatus.UNKNOWN

    def get_status(self, vms: list[VMConfig]) -> None:
        self.server_cache = {
            server.name: server
            for server in self.client.servers.get_all(label_selector="vulnhost")
            if server.name is not None
        }
        for vm in vms:
            name = server_name(vm)
            if name not in self.server_cache:
                vm.status = VMStatus.MISSING
            else:
                cached = self.server_cache[name]
                vm.status = self.status_to_vmstatus(cached.status)
                vm.backend_options["hetzner_status"] = cached.status
                if cached.public_net is not None:
                    vm.ip = cached.public_net.ipv4.ip
                    vm.backend_options["ssh_active"] = check_ssh_active(
                        cached.public_net.ipv4.ip
                    )
                if cached.server_type is not None:
                    vm.backend_options["server_type"] = cached.server_type.name
                self.check_blocking_actions(vm)

    def get_server(self, vm: VMConfig) -> BoundServer | None:
        name = server_name(vm)
        if name in self.server_cache:
            return self.server_cache[name]
        server = self.client.servers.get_by_name(name)
        if server is not None:
            self.server_cache[name] = server
        return server

    def check_blocking_actions(self, vm: VMConfig) -> None:
        remove_actions = []
        for action in self.running_actions[server_name(vm)]:
            if action.status != Action.STATUS_SUCCESS:
                action.reload()
            if action.status != Action.STATUS_RUNNING:
                remove_actions.append(action)
        for action in remove_actions:
            self.running_actions[server_name(vm)].remove(action)

    def has_blocking_actions(self, vm: VMConfig) -> bool:
        return len(self.running_actions[server_name(vm)]) > 0

    def create_vm(self, vm: VMConfig) -> VMConfig:
        vm2 = vm.clone_minimal()
        cloudinit: dict[str, Any] = {
            "runcmd": ["sed '/^root/s/:0:0:99999:/:1:0:99999:/' -i /etc/shadow"]
        }  # initial command to remove "root user password reset" problem
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
        server_type = vm.backend_options.get("server_type", self.config["server_type"])
        images = [
            image
            for image in self.client.images.get_all()
            if image.name == self.config["image_name"]
            or image.description == self.config["image_name"]
        ]
        if len(images) == 0:
            raise Exception("Image not found")
        if len(images) > 1:
            raise Exception("Image description not unique")
        firewalls: list[Firewall | BoundFirewall] = []
        if "firewall" in self.config:
            fw = self.client.firewalls.get_by_name(self.config["firewall"])
            if fw is not None:
                firewalls.append(fw)

        response = self.client.servers.create(
            server_name(vm),
            server_type=ServerType(name=server_type),
            image=images[0],
            location=Location(name=self.config.get("location", "fsn1")),
            labels={"vulnhost": self.config.get("label", "vulnhost")},
            user_data=cloudinit_str,
            start_after_create=(vm.status == VMStatus.RUNNING),
            firewalls=firewalls,
        )
        vm2.root_password = response.root_password
        if response.server.public_net is not None:
            vm2.ip = response.server.public_net.ipv4.ip
        vm2.backend_options["server_type"] = server_type
        return vm2

    def destroy_vm(self, vm: VMConfig) -> None:
        server = self.get_server(vm)
        if server:
            server.delete()

    def start_vm(self, vm: VMConfig) -> VMStatus:
        server = self.get_server(vm)
        if server and server.status in ("off", "unknown"):
            server.power_on()
            return VMStatus.BOOTING
        return vm.status

    def stop_vm(self, vm: VMConfig) -> VMStatus:
        server = self.get_server(vm)
        if server and server.status in ("starting", "running"):
            server.shutdown()
            return VMStatus.BUSY
        return vm.status

    def reboot_vm(self, vm: VMConfig) -> bool:
        server = self.get_server(vm)
        if server and server.status in ("starting", "running"):
            server.reboot()
            return True
        return False

    def reset_vm(self, vm: VMConfig) -> VMConfig:
        server = self.get_server(vm)
        if server:
            images = [
                image
                for image in self.client.images.get_all()
                if image.name == self.config["image_name"]
                or image.description == self.config["image_name"]
            ]
            if len(images) == 0:
                raise Exception("Image not found")
            if len(images) > 1:
                raise Exception("Image description not unique")
            server.rebuild(images[0])
            # self.running_actions[self.server_name(vm)].append(response)
            vm.status = VMStatus.BUSY
            # There's a bug in Hetzner's python library, we don't get the root password back after rebuild.
            # Workaround: remove password for rebuild, and trigger another password reset
            # (will execute once VM is "RUNNING" again)
            vm.root_password = None
            vm.action_counters["reset_root_password"] = -1
            # cloudinit is running, files changed since then need updates
            for fname in vm.backend_options.get("changed_files_after_cloudinit", []):
                vm.files.pop(fname, None)
            vm.backend_options["changed_files_after_cloudinit"] = []
            if vm.backend_options.get("changed_sshkey_after_cloudinit", False):
                vm.sshkey = None
                del vm.backend_options["changed_sshkey_after_cloudinit"]
        return vm

    def reset_root_password(self, vm: VMConfig) -> bool:
        if self.has_blocking_actions(vm):
            return False
        server = self.get_server(vm)
        if server:
            response = server.reset_password()
            try:
                response.action.wait_until_finished(3)
                if response.root_password:
                    vm.root_password = response.root_password
                if response.action.status == Action.STATUS_SUCCESS:
                    return True
            except ActionTimeoutException:
                self.logger.error("[ERR] Action timeout (password reset)")
            except ActionFailedException:
                self.logger.error("[ERR] Action failed (password reset)")
        return False

    def set_sshkeys(self, vm: VMConfig, keys: str) -> None:
        if not keys.endswith("\n"):
            keys += "\n"
        cmd = f"echo {base64.b64encode(keys.encode()).decode()} | base64 -d > /root/.ssh/authorized_keys"
        rc, _, err = run_ssh_command(vm, cmd)
        if rc == 0:
            vm.sshkey = keys
            vm.backend_options["changed_sshkey_after_cloudinit"] = True
            self.logger.info(f"[OK] SSH key for VM {server_name(vm)} changed")
        else:
            self.logger.error(f"[ERR] Could not change SSH keys: rc {rc}")
            self.logger.error("> " + cmd + "\n" + err.decode().strip())

    def set_root_password(self, vm: VMConfig, password: str) -> None:
        _ = (vm, password)
        # not implemented
        self.logger.error("Not implemented: Hetzner set_root_password")
        ...

    def set_files(self, vm: VMConfig, files: dict[str, FileConfig]) -> None:
        for fname, fc in files.items():
            if fname in vm.files and vm.files[fname] == fc:
                continue
            cmd = f"echo '{base64.b64encode(fc.content.encode()).decode()}' | base64 -d > {shlex.quote(fname)}"
            if fc.owner:
                cmd += f" && chown {shlex.quote(fc.owner)} {shlex.quote(fname)}"
            if fc.permission:
                cmd += f" && chmod {shlex.quote(fc.permission)} {shlex.quote(fname)}"
            rc, _, err = run_ssh_command(vm, cmd)
            if rc == 0:
                vm.files[fname] = fc.clone()
                if "changed_files_after_cloudinit" not in vm.backend_options:
                    vm.backend_options["changed_files_after_cloudinit"] = []
                if fname not in vm.backend_options["changed_files_after_cloudinit"]:
                    vm.backend_options["changed_files_after_cloudinit"].append(fname)
                self.logger.info(f"[OK] File {fname} on VM {server_name(vm)} changed")
            else:
                self.logger.error(f'[ERR] Could not write file "{fname}": rc {rc}')
                self.logger.error("> " + cmd + "\n" + err.decode().strip())

    def transform_backend_options(self, vm: VMConfig, options: dict) -> None:
        new_server_type = options.get("server_type", "")
        if (
            new_server_type
            and vm.backend_options.get("server_type", "") != new_server_type
        ):
            server = self.get_server(vm)
            if server and server.status == "off" and vm.status != VMStatus.BUSY:
                hetzner_server_type = self.client.server_types.get_by_name(
                    new_server_type
                )
                if hetzner_server_type is None:
                    raise ValueError(f"Invalid hetzner server type: {new_server_type}")
                server.change_type(hetzner_server_type, False)
                vm.status = VMStatus.BUSY
                time.sleep(0.1)
                self.logger.info(
                    f"[OK] Rescaled server {server_name(vm)} to server type {new_server_type}"
                )

    def _manual_api_request(self, endpoint: str, params: dict) -> requests.Response:
        endpoint = endpoint.lstrip("/")
        headers = {
            "User-Agent": self.client._get_user_agent(),
            "Authorization": "Bearer {token}".format(token=self.client.token),
        }
        t = time.monotonic()
        self.logger.debug(f"GET {endpoint}...")
        response = requests.get(
            f"https://api.hetzner.cloud/{endpoint}",
            headers=headers,
            params=params,
            timeout=10,
        )
        self.logger.debug(f"GET {endpoint} => {response.status_code}")
        if response.status_code != 200:
            raise Exception(f"Error {response.status_code}: {response.text}")
        if time.monotonic() - t > 3:
            self.logger.warning(
                f"Request to hetzner {endpoint} took {time.monotonic() - t:.1f} seconds"
            )
        return response

    def get_statistics(self, vm: VMConfig) -> list[dict]:
        results: list[dict] = []
        servername = server_name(vm)
        if servername not in self.server_cache:
            return results
        server = self.server_cache[servername]
        if server:
            now = datetime.datetime.now(tz=datetime.timezone.utc).replace(microsecond=0)
            start = now - datetime.timedelta(minutes=10)
            if (
                servername in self.last_statistics_query
                and self.last_statistics_query[servername] > start
            ):
                start = self.last_statistics_query[servername]
            params = {
                "step": "60",
                "type": "cpu,disk,network",
                "start": start.isoformat(),
                "end": now.isoformat(),
            }
            response = self._manual_api_request(
                f"/v1/servers/{server.id}/metrics", params=params
            )
            if response.status_code != 200:
                raise Exception(f"Error {response.status_code}: {response.text}")

            self.last_statistics_query[servername] = now

            # remaining requests
            remaining = int(response.headers["RateLimit-Remaining"])
            if self.ratelimit_remaining is None or remaining < self.ratelimit_remaining:
                self.ratelimit_remaining = remaining
            self.ratelimit_limit = int(response.headers["RateLimit-Limit"])
            self.ratelimit_reset = int(response.headers["RateLimit-Reset"])

            # encode for gameserver
            metrics = response.json()["metrics"]["time_series"]
            tags = {
                "backend": self.name,
                "teamid": str(vm.team),
                "server": server_name(vm),
            }
            data: dict[float, dict[str, Any]] = defaultdict(dict)
            for name, values in metrics.items():
                for ts, value in values["values"]:
                    data[ts][name] = value
            for ts, fields in data.items():
                results.append(
                    {
                        "metric": "vulnboxes",
                        "attributes": tags,
                        "values": fields,
                        "ts": ts,
                    }
                )
        return results

    def statistics_start(self) -> None:
        self.ratelimit_remaining = None
        self.ratelimit_reset = None

    def statistics_finished(self) -> list[dict]:
        ts = time.time()
        tags = {"backend": self.name}

        status = {k: 0 for k in VMStatus}
        for server in self.server_cache.values():
            status[self.status_to_vmstatus(server.status)] += 1
        result = [
            {
                "metric": "cloud_servers",
                "attributes": tags,
                "ts": ts,
                "values": {"servers": len(self.server_cache)}
                | {str(k).split(".")[-1]: v for k, v in status.items()},
            }
        ]

        if self.ratelimit_remaining is not None:
            result.append(
                {
                    "metric": "hetzner_rates",
                    "attributes": tags,
                    "ts": ts,
                    "values": {
                        "limit": self.ratelimit_limit,
                        "remaining": self.ratelimit_remaining,
                        "reset": self.ratelimit_reset,
                    },
                }
            )

        return result

    def statistics_is_overloaded(self) -> bool:
        if (
            self.ratelimit_remaining is not None
            and self.ratelimit_remaining < self.ratelimit_overloaded
        ):
            self.ratelimit_overloaded -= 120
            return True
        return False
