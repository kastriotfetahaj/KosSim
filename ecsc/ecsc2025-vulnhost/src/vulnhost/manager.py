import datetime
import json
import logging
import os
import time
import traceback
from collections import defaultdict
from concurrent.futures import Executor, wait, ThreadPoolExecutor, Future
from typing import Callable, ParamSpec, TypeVar, Any

from .backends.backend import VMBackend, get_backend
from .config_format import StatusConfig, VMConfig, VMStatus, load_config

P = ParamSpec("P")
T = TypeVar("T")


class VulnhostManager:
    def __init__(self, status_file: str, executor: Executor) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.backends: dict[str, VMBackend] = {}
        self.executor = executor
        self.status_file = status_file
        self.config_url: str | None = None
        self.status_url: str | None = None
        self.statistics_url: str | None = None
        self.statistics_interval: int | None = None
        self.current_state = StatusConfig(vms=[])
        self.dump_states = False
        if os.path.exists(status_file):
            with open(status_file, "r") as f:
                self.last_status_file: str | None = f.read()
                self.current_state = load_config(self.last_status_file)
        else:
            self.last_status_file = None

    def save(self) -> None:
        dump = (
            self.current_state.dump(indent=4, sort_keys=True)
            if self.dump_states
            else self.current_state.dump()
        )
        if self.dump_states and dump != self.last_status_file:
            d = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            with open(f"/tmp/status_{d}.json", "w") as f2:
                f2.write(dump)
        try:
            with open(self.status_file, "w") as f:
                f.write(dump)
        except (IOError, OSError):
            time.sleep(1)
            with open(self.status_file, "w") as f:
                f.write(dump)

    def load_backends(self, fname: str) -> None:
        with open(fname, "r") as f:
            for name, config in json.loads(f.read()).items():
                if name == "config_url":
                    self.config_url = config
                elif name == "status_url":
                    self.status_url = config
                elif name == "statistics_url":
                    self.statistics_url = config
                elif name == "statistics_interval":
                    self.statistics_interval = config
                else:
                    self.backends[name] = get_backend(config["backend"], name, config)

    def update_states(self) -> None:
        d = defaultdict(list)
        for vm in self.current_state.vms:
            d[vm.kind].append(vm)
        for l in d.values():
            backend: VMBackend = self.backends[l[0].kind]
            backend.get_status(l)

    def transform_to_target_status(self, target_state: StatusConfig) -> None:
        actions: list[tuple[Callable, tuple]] = []
        seen_vms = []
        missing_vms = []
        for vm in target_state.vms:
            current_vm = self.current_state.get_matching_vm(vm)
            seen_vms.append(current_vm)
            if current_vm is None or current_vm.status == VMStatus.MISSING:
                actions.append((self.create_vm, (vm,)))
                if current_vm:
                    missing_vms.append(current_vm)
            else:
                actions.append((self.transform_vm, (current_vm, vm)))
        for vm in self.current_state.vms:
            if vm not in seen_vms:
                actions.append((self.remove_vm, (vm,)))
        for vm in missing_vms:
            self.current_state.vms.remove(vm)
        futures = [self.executor.submit(method, *args) for method, args in actions]
        self.logger.debug(f"submitting {len(actions)} actions to executor...")
        done, not_done = wait(futures)
        self.logger.debug(f"retrieved {len(actions)} results from executor")
        for future, (method, args) in zip(futures, actions):
            exc = future.exception()
            if exc:
                self.logger.error(
                    "Task failed: " + str(exc) + " in " + repr(method) + "\n",
                    exc_info=exc,
                )
                with open("errorlog.log", "a+") as errorlog:
                    errorlog.write("Method = " + repr(method) + "\n")
                    errorlog.write("Arguments = " + repr(args) + "\n")
                    errorlog.write("Exception = " + repr(exc) + "\n")
                    errorlog.write(
                        "".join(
                            traceback.TracebackException.from_exception(exc).format()
                        )
                    )
                    errorlog.write("\n\n")

    def create_vm(self, new_vm: VMConfig) -> None:
        backend = self.backends[new_vm.kind]
        self.logger.info(f'     Creating VM "{new_vm.kind}" for team {new_vm.team} ...')
        vm = backend.create_vm(new_vm)
        self.current_state.vms.append(vm)
        self.logger.info(f'[OK] Created VM "{new_vm.kind}" for team {new_vm.team}.')
        self.transform_vm(vm, new_vm)

    def remove_vm(self, old_vm: VMConfig) -> None:
        backend = self.backends[old_vm.kind]
        self.logger.info(f'     Removing VM "{old_vm.kind}" for team {old_vm.team} ...')
        backend.destroy_vm(old_vm)
        self.current_state.vms.remove(old_vm)
        self.logger.info(f'[OK] Removed VM "{old_vm.kind}" for team {old_vm.team}.')

    def transform_vm_properties(self, old_vm: VMConfig, new_vm: VMConfig) -> None:
        backend = self.backends[old_vm.kind]
        if (old_vm.sshkey or "").strip() != (new_vm.sshkey or "").strip():
            backend.set_sshkeys(old_vm, new_vm.sshkey or "")
        if old_vm.root_password != new_vm.root_password and new_vm.root_password:
            backend.set_root_password(old_vm, new_vm.root_password)
        if old_vm.files != new_vm.files:
            backend.set_files(old_vm, new_vm.files)
        if old_vm.backend_options != new_vm.backend_options:
            backend.transform_backend_options(old_vm, new_vm.backend_options)

    def transform_vm(self, old_vm: VMConfig, new_vm: VMConfig) -> None:
        """
        :param old_vm: The current status
        :param new_vm: The desired status
        :return:
        """
        # Update properties (1)
        self.transform_vm_properties(old_vm, new_vm)
        # Update status
        backend = self.backends[old_vm.kind]
        # check for resets
        if old_vm.action_counters.get("reset", 0) < new_vm.action_counters.get(
            "reset", 0
        ):
            vm2 = backend.reset_vm(old_vm)
            if vm2 != old_vm:
                self.current_state.vms.remove(old_vm)
                self.current_state.vms.append(vm2)
                old_vm = vm2
            old_vm.action_counters["reset"] = new_vm.action_counters["reset"]
            self.logger.info(f'[OK] Reset VM "{old_vm.kind}" for team {old_vm.team}.')
        # check for reboots
        if (
            old_vm.action_counters.get("reboot", 0)
            < new_vm.action_counters.get("reboot", 0)
            and old_vm.status == VMStatus.RUNNING
        ):
            self.logger.info(
                f'     Rebooting VM "{old_vm.kind}" for team {old_vm.team} ...'
            )
            if backend.reboot_vm(old_vm):
                old_vm.action_counters["reboot"] = new_vm.action_counters["reboot"]
                self.logger.info(
                    f'[OK] Reboot VM "{old_vm.kind}" for team {old_vm.team}.'
                )
        # check for password resets
        if (
            old_vm.action_counters.get("reset_root_password", 0)
            < new_vm.action_counters.get("reset_root_password", 0)
            and old_vm.status == VMStatus.RUNNING
        ):
            self.logger.info(
                f'     Resetting root password in VM "{old_vm.kind}" for team {old_vm.team} ...'
            )
            if backend.reset_root_password(old_vm):
                old_vm.action_counters["reset_root_password"] = new_vm.action_counters[
                    "reset_root_password"
                ]
                self.logger.info(
                    f'[OK] Reset root password in VM "{old_vm.kind}" for team {old_vm.team}.'
                )
        # check for start/stop
        if (
            old_vm.status != new_vm.status
            and new_vm.status != VMStatus.UNKNOWN
            and old_vm.status not in (VMStatus.BUSY, VMStatus.CREATING)
        ):
            if new_vm.status == VMStatus.STOPPED:
                self.logger.info(
                    f'     Stopping vm "{new_vm.kind}" for team {new_vm.team} ...'
                )
                old_vm.status = backend.stop_vm(old_vm)
                self.logger.info(
                    f'[OK] Stopped vm "{new_vm.kind}" for team {new_vm.team}.'
                )
            elif new_vm.status == VMStatus.RUNNING:
                self.logger.info(
                    f'     Starting vm "{new_vm.kind}" for team {new_vm.team} ...'
                )
                old_vm.status = backend.start_vm(old_vm)
                self.logger.info(
                    f'[OK] Started vm "{new_vm.kind}" for team {new_vm.team}.'
                )
        # Update properties (2)
        self.transform_vm_properties(old_vm, new_vm)

    def retrieve_statistics(self, *, short: bool = False) -> list[dict]:
        statistics: list[dict] = []
        for backend in self.backends.values():
            backend.statistics_start()

        # fetch per-box statistics
        if not short:
            actions = []
            for vm in self.current_state.vms:
                if vm.status == VMStatus.RUNNING:
                    backend = self.backends[vm.kind]
                    actions.append((backend.get_statistics, (vm,)))
            futures = [self.executor.submit(method, *args) for method, args in actions]
            done, not_done = wait(futures, timeout=90)
            if len(not_done) > 0:
                self.logger.warning(
                    f"{len(not_done)}/{len(futures)} statistics requests did not complete in time"
                )
                for x in not_done:
                    x.cancel()  # currently running task will keep running...
            for future in done:
                exc = future.exception()
                if exc:
                    self.logger.error("Task failed: " + str(exc) + "\n", exc_info=exc)
                else:
                    statistics += future.result()

        for backend in self.backends.values():
            statistics += backend.statistics_finished()

        # if api limit are going to be reached soon - increase statistics interval
        if not short and any(
            backend.statistics_is_overloaded() for backend in self.backends.values()
        ):
            if self.statistics_interval is not None:
                self.logger.info(
                    f"To reduce API limit usage, statistics interval will be set "
                    f"from {self.statistics_interval} to {self.statistics_interval + 15}"
                )
                self.statistics_interval += 15

        return statistics


class DryRunExecutor(ThreadPoolExecutor):
    def __init__(self) -> None:
        super().__init__(1)

    def submit(
        self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs
    ) -> Future:
        return super().submit(self.printer, fn, args, **kwargs)

    def printer(self, fn: Callable, args: Any, **kwargs: Any) -> None:
        logging.info("Action:", fn.__name__, "for team", args[0].team)
