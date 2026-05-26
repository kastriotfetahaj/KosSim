import base64
import json
import os
import re
from functools import cache
from logging import getLogger

from constance import config as constance_config
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from mainpage.models import VM, Interface, Peer, Player, TeamProfile, VMStatusLog
from mainpage.network_lib import get_wireguard_config
from mainpage.utils import hosting_token_required, player_required, technician_required
from mainpage.vmtemplate import VmTemplate

LOGGER = getLogger(__name__)

@cache
def read_file_cached(fname: str) -> str:
    with open(fname, "r") as f:
        return f.read()


def get_vms_for_view(request: HttpRequest) -> list[tuple[VmTemplate, VM | bool]]:
    team = Player.objects.get(id=request.user.id).team
    db_vms = {vm.kind: vm for vm in VM.objects.filter(team_id=team.team_id).all()}
    return [
        (tmpl, db_vms.get(tmpl.template["kind"], False))
        for tmpl in settings.HOSTING_VM_TEMPLATES
    ]


def get_vms_for_admin_view(
    request: HttpRequest,
) -> list[tuple[str, VmTemplate, VM | bool, TeamProfile]]:
    db_vms = {
        (vm.kind, vm.team_id): vm for vm in VM.objects.order_by("team_id", "kind").all()
    }
    teams = TeamProfile.objects.filter(team_id__isnull=False).order_by("team_id").all()
    return [
        (
            f'{tmpl.name} for team #{str(team.team_id)} "{team.name}"',
            tmpl,
            db_vms.get((tmpl.template["kind"], team.team_id), False),  # type: ignore
            team,
        )
        for team in teams
        for tmpl in settings.HOSTING_VM_TEMPLATES
    ]


@hosting_token_required
def vms_config(request: HttpRequest):
    vms = VM.objects.order_by("kind", "team_id")
    if "backends" in request.GET:
        vms.filter(kind__in=request.GET["backends"].split(","))
    result = []
    for vm in vms:
        valid = True
        config = vm.config
        if config["status"] == "MISSING":
            continue
        # patch in configuration file content
        for f in config.get("files", {}).values():
            if f["content"] == "{{ssh_keys}}":
                keys = constance_config.HOSTING_ORGA_KEYS.split(
                    "\n"
                ) + vm.team.ssh_keys.split("\n")
                f["content"] = "\n".join(keys).strip()
            if f["content"] == "{{vpn_config_file}}":
                if not settings.VPN_CONFIG_PATH:
                    valid = False
                    break
                fname = (
                    settings.VPN_CONFIG_PATH + f"/client-team{vm.team_id}-vulnbox.conf"
                )
                if not os.path.exists(fname):
                    valid = False
                    break
                f["content"] = read_file_cached(fname)
            if f["content"] == "{{wireguard_config_file}}":
                team_interface = Interface.objects.filter(team_id=vm.team.id).get()
                # We assume that there is exactly one of the given type per team!
                try:
                    peer = Peer.objects.filter(
                        interface_id=team_interface.id,
                        type=vm.kind,
                    ).get()
                except (Peer.DoesNotExist, Peer.MultipleObjectsReturned):
                    LOGGER.warning(f"Could not find wireguard peer for {vm}")
                    valid = False
                    break

                f["content"] = get_wireguard_config(peer)

        if config.get("sshkey", "") == "{{ssh_keys}}":
            config["sshkey"] = "\n".join(
                constance_config.HOSTING_ORGA_KEYS.split("\n")
                + vm.team.ssh_keys.split("\n")
            ).strip()

        if valid:
            result.append(config)
    return JsonResponse({"vms": result})


@require_POST
@csrf_exempt
@hosting_token_required
def vms_status(request: HttpRequest):
    status_vms = json.loads(request.body)["vms"]
    db_vms: dict[tuple[str, int], VM] = {
        (vm.kind, vm.team_id): vm for vm in VM.objects.all()
    }
    vms_in_status_report = set()
    for vmstatus in status_vms:
        vms_in_status_report.add((vmstatus["kind"], vmstatus["team"]))
        if (vmstatus["kind"], vmstatus["team"]) not in db_vms:
            continue
        vm = db_vms[vmstatus["kind"], vmstatus["team"]]
        if vm.status != vmstatus:
            print("Status update:", vm.status, vmstatus)
            create_status_log(vm.kind, vm.team_id, vm.status, vmstatus)
            vm.status = vmstatus
            vm.save()
    for k, dbvm in db_vms.items():
        # delete VMs that *should* be missing (and are not reported back)
        if dbvm.config["status"] == "MISSING" and k not in vms_in_status_report:
            if dbvm.status["status"] != "MISSING":
                for log in get_vm_logs(
                    dbvm.kind, dbvm.team_id, "status", dbvm.status["status"], "MISSING"
                ):
                    log.save()
            dbvm.delete()
    return JsonResponse({"ok": True})


def create_status_log(
    kind: str, team_id: int, old_status: dict, new_status: dict
) -> None:
    logs = []
    for k, ov in old_status.items():
        nv = new_status[k] if k in new_status else None
        logs += get_vm_logs(kind, team_id, k, ov, nv)
    for k, nv in new_status.items():
        if k not in old_status:
            logs += get_vm_logs(kind, team_id, k, None, nv)
    if logs:
        VMStatusLog.objects.bulk_create(logs)


def get_vm_logs(
    kind: str, team_id: int, field: str, old_value, new_value
) -> list[VMStatusLog]:
    if field in ("team", "kind", "files") or old_value == new_value:
        return []

    log = VMStatusLog(
        kind=kind,
        team_id=team_id,
        field=field,
        old_value=old_value,
        new_value=new_value,
    )
    # get message
    if field == "status":
        # 'MISSING', 'STOPPED', 'RUNNING', 'CREATING', 'BOOTING', 'BUSY'
        if new_value == "MISSING":
            log.message = "VM removed"
        elif old_value == "MISSING":
            if new_value == "STOPPED":
                log.message = "VM created, but not started"
            elif new_value == "RUNNING":
                log.message = "VM created and started"
            elif new_value == "CREATING":
                log.message = "VM creating"
            elif new_value == "BOOTING":
                log.message = "VM created and booting"
            elif new_value == "BUSY":
                log.message = "VM created"
        elif new_value == "STOPPED":
            log.message = "VM stopped"
        elif new_value == "RUNNING":
            log.message = "VM started"
        elif new_value == "CREATING":
            log.message = "VM creating"
        elif new_value == "BOOTING":
            log.message = "VM booting"
        elif new_value == "BUSY":
            log.message = "VM is busy"

    elif field == "sshkey":
        log.message = (
            "SSH authorized keys changed"
            if old_value is not None
            else "SSH authorized keys initialized"
        )
    elif field == "root_password":
        log.message = (
            "Root password changed"
            if old_value is not None
            else "Root password created"
        )
    elif field == "ip":
        if old_value is not None:
            log.message = "Public IP changed"
        else:
            return []
    elif field == "action_counters":
        if not new_value or not old_value:
            return []
        logs = []
        for k, v in new_value.items():
            if k not in old_value or old_value[k] == v:
                continue
            log = VMStatusLog(
                kind=kind,
                team_id=team_id,
                field=field + "." + k,
                old_value=old_value[k],
                new_value=new_value[k],
            )
            if k == "reset":
                log.message = "VM wiped and rebuilding"
            elif k == "reboot":
                log.message = "VM rebooted"
            elif k == "reset_root_password":
                log.message = "Requested root password reset"
            logs.append(log)
        return logs

    elif field == "backend_options":
        if not old_value:
            old_value = {}
        if not new_value:
            new_value = {}
        logs = []
        for k, v in new_value.items():
            ov = old_value[k] if k in old_value else None
            if ov != v:
                log = VMStatusLog(
                    kind=kind,
                    team_id=team_id,
                    field=field + "." + k,
                    old_value=ov,
                    new_value=v,
                )
                if k == "server_type" and ov and v:
                    log.message = "VM rescaled"
                logs.append(log)
        return logs

    return [log]


@require_POST
@login_required
@player_required
@technician_required
def edit_ssh_key(request: HttpRequest, player: Player) -> HttpResponse:
    team = player.team
    if not team:
        messages.error(request, "Not a team")
        return redirect(reverse("team"))

    lines = [line.strip() for line in request.POST["sshkeys"].split("\n")]
    # validate lines
    ssh_key_count = 0
    for i, line in enumerate(lines):
        if not line:
            continue
        if line.startswith("#"):
            continue
        if re.match(
            r"(sk-)?(ssh-rsa|ecdsa-sha2-nistp256|ecdsa-sha2-nistp521|ssh-ed25519|ssh-dss)(@openssh\.com)? AAAA[0-9A-Za-z+/]+[=]{0,3}( [^@]+@[^@]+)?",
            line,
        ):
            ssh_key_count += 1
        else:
            messages.error(request, f'Invalid ssh key in line {i + 1} ("{line}")')
            return redirect(reverse("team"))

    team.ssh_keys = "\n".join(lines)
    team.save()
    messages.success(request, f"{ssh_key_count} ssh keys have been saved.")
    return redirect(reverse("team"))


@require_POST
@login_required
def vm_action(request: HttpRequest) -> HttpResponse:
    action = request.POST["action"]
    kind = request.POST["vm_kind"]
    team_profile: TeamProfile | None = None
    player: Player | None = Player.objects.filter(id=request.user.id).first()
    if player is not None and player.is_at_least_technician:
        team_profile = player.team
    if (
        request.user.is_staff or request.user.is_superuser
    ) and "team_id" in request.POST:
        team_profile = TeamProfile.objects.filter(
            team_id=request.POST["team_id"]
        ).first()
    if not team_profile:
        messages.error(request, "No team found / insufficient privileges")
        return redirect(reverse("index"))

    tmpl: VmTemplate = [
        tmpl for tmpl in settings.HOSTING_VM_TEMPLATES if tmpl.template["kind"] == kind
    ][0]
    vm: VM | None = VM.objects.filter(kind=kind, team_id=team_profile.team_id).first()
    is_admin = request.user.is_staff or request.user.is_superuser

    if not is_admin and not tmpl.control_available:
        messages.error(request, "Control not available")

    elif action == "create":
        if vm:
            messages.error(request, "VM already exists")
        else:
            vm_create(team_profile, tmpl)
            messages.success(request, "VM is being created now ...")

    elif action == "destroy":
        if not vm:
            messages.error(request, "VM does not exist")
        else:
            vm_destroy(vm)
            messages.success(request, "VM is being destructed.")

    elif action == "reboot":
        if not vm:
            messages.error(request, "VM does not exist")
        elif vm.config["status"] == "STOPPED" and not is_admin:
            messages.error(request, "Permission error")
        else:
            vm_request_action(vm, "reboot")
            messages.success(request, "VM is rebooting ...")

    elif action == "reset":
        if not vm:
            messages.error(request, "VM does not exist")
        else:
            vm_request_action(vm, "reset")
            messages.success(request, "VM is being reset ...")

    elif action == "reset_root_password":
        if not vm:
            messages.error(request, "VM does not exist")
        else:
            vm_request_action(vm, "reset_root_password")
            messages.success(request, "VM root password is being reset ...")

    elif action == "start" and is_admin:
        if vm is not None:
            vm_start(vm)
            messages.success(request, "VM will start soon ...")
        else:
            messages.error(request, "VM does not exist")

    elif action == "shutdown" and is_admin:
        if vm is not None:
            vm_shutdown(vm)
            messages.success(request, "VM will be stopped ...")
        else:
            messages.error(request, "VM does not exist")

    else:
        messages.error(request, "Invalid command")

    if "/vm_list" in request.headers.get("Referer", ""):
        return redirect(reverse("vm_list"))
    return redirect(reverse("team") + "#vms")


def vm_create(team: TeamProfile, tmpl: VmTemplate, status="RUNNING") -> None:
    if team.team_id is None:
        raise ValueError("Team ID is required")
    config = {k: v for k, v in tmpl.template.items()}
    config["team"] = team.team_id
    config["status"] = status
    if config.get("root_password", "") == "{{generate}}":
        config["root_password"] = base64.urlsafe_b64encode(os.urandom(12)).decode()
    status = {"kind": config["kind"], "team": team.team_id, "status": "CREATING"}
    kind=tmpl.template["kind"]

    team_interface = Interface.objects.filter(team_id=team.id).get()
    # We assume that there is exactly one of the given type per team!
    try:
        peer = Peer.objects.filter(
            interface_id=team_interface.id,
            type=kind,
        ).get()
    except (Peer.DoesNotExist, Peer.MultipleObjectsReturned) as e:
        LOGGER.warning(f"Could not find {kind.label} wireguard peer for team {team.id}")
        raise e

    vm = VM(
        kind=tmpl.template["kind"],
        team_id=team.team_id,
        config=config,
        status=status,
        metadata={"vpn_ip": peer.cidr}
    )
    vm.save()
    for log in get_vm_logs(
        kind=tmpl.template["kind"],
        team_id=team.team_id,
        field="status",
        old_value="MISSING",
        new_value="CREATING",
    ):
        log.save()


def vm_destroy(vm: VM):
    vm.config["status"] = "MISSING"
    vm.save()
    # vm.delete()


def vm_shutdown(vm: VM):
    vm.config["status"] = "STOPPED"
    vm.save()


def vm_start(vm: VM):
    vm.config["status"] = "RUNNING"
    vm.save()


def vm_request_action(vm: VM, action: str):
    rc1 = vm.config.get("action_counters", {}).get(action, 0)
    rc2 = vm.status.get("action_counters", {}).get(action, 0)
    if rc1 <= rc2:
        if "action_counters" not in vm.config:
            vm.config["action_counters"] = {}
        vm.config["action_counters"][action] = rc2 + 1
        vm.save()


@require_POST
@login_required
def vm_admin(request):
    if not request.user.is_superuser:
        return HttpResponse("", status=403)
    action = request.POST["action"]
    vms = VM.objects.all()

    if action == "create_all":
        db_vms = {(vm.kind, vm.team_id): vm for vm in vms}
        teams = TeamProfile.objects.filter(team_id__isnull=False).all()
        counter = 0
        for tmpl in settings.HOSTING_VM_TEMPLATES:
            for team in teams:
                if (tmpl.template["kind"], team.team_id) not in db_vms:
                    vm_create(team, tmpl, status="STOPPED")
                    counter += 1
        messages.success(
            request, f"Created {counter} VMs (stopped, please start them) ..."
        )

    elif action == "reboot_all":
        for vm in vms:
            vm_request_action(vm, "reboot")
        messages.success(request, f"Rebooting {len(vms)} VMs ...")
    elif action == "reset_all":
        for vm in vms:
            vm_request_action(vm, "reset")
        messages.success(request, f"Resetting {len(vms)} VMs ...")
    elif action == "shutdown_all":
        vms = [vm for vm in vms if vm.config["status"] != "STOPPED"]
        for vm in vms:
            vm_shutdown(vm)
        messages.success(request, f"Shutdown {len(vms)} VMs ...")
    elif action == "start_all":
        vms = [vm for vm in vms if vm.config["status"] == "STOPPED"]
        for vm in vms:
            vm_start(vm)
        messages.success(request, f"Started {len(vms)} VMs ...")
    elif action == "destroy_all":
        vms = [vm for vm in vms if vm.config["status"] != "MISSING"]
        for vm in vms:
            vm_destroy(vm)
        messages.success(request, f"Destroyed {len(vms)} VMs ...")

    return redirect(reverse("vm_list"))
