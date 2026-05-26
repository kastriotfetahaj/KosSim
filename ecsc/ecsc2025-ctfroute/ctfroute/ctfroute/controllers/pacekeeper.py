__all__ = ["PaceKeeper"]

import asyncio
import logging
from pprint import pformat
from typing import NamedTuple

from ctfroute.controllers.base import Controller, InternalUpdate
from ctfroute.controllers.concierge import Concierge
from ctfroute.drivers.netfilter.driver import NetfilterPaceDriver
from ctfroute.exceptions import CtfRouteException
from ctfroute.state.external import (
    HTBClass,
    HTBClassTemplate,
    NetEntity,
    TeamId,
)
from ctfroute.state.internal import Team
from ctfroute.utils import EntityType

LOGGER = logging.getLogger(__name__)

DEFAULT_CLASS = 0
DEFAULT_CLASSES = (DEFAULT_CLASS, DEFAULT_CLASS + 1)
MAX_TC_CLASS_ID = 0xFFFF

IfName = str
ClassId = int
NftMatcher = str
NftMatchers = frozenset[str]
Params = str
QDisc = str


class TCCommandError(CtfRouteException): ...


class PaceKeeper(Controller):
    """
    Ensures acceptable network utilization (traffic control).

    PaceKeeper keeps the peace by ensuring noone exceeds the acceptable pace in the
    network.
    """

    class KEYS(NamedTuple):
        INITIALIZED: str

    def _get_team_matchers(self, team: Team) -> tuple[NftMatchers, NftMatchers]:
        return (
            frozenset({f"ip saddr {team.network} ct direction original"}),
            frozenset({f"ip saddr {team.network} ct direction reply"}),
        )

    def _get_entitiy_matchers(
        self, entity: NetEntity
    ) -> tuple[NftMatchers, NftMatchers]:
        orig_matchers = set()
        reply_matchers = set()

        if entity.addresses:
            for net in entity.addresses:
                orig_matchers.add(f"ip saddr {net} ct direction original")
                reply_matchers.add(f"ip saddr {net} ct direction reply")

        return frozenset(orig_matchers), frozenset(reply_matchers)

    def _get_class_matchers(self, cls: HTBClass) -> tuple[NftMatchers, NftMatchers]:
        orig_matchers = set()
        reply_matchers = set()
        if cls.addresses:
            orig_matchers |= {
                f"ip saddr {addr} ct direction original" for addr in cls.addresses
            }
            reply_matchers |= {
                f"ip saddr {addr} ct direction reply" for addr in cls.addresses
            }
        if cls.match:
            for match in cls.match:
                orig_matchers.add(f"{match} ct direction original")
                reply_matchers.add(f"{match} ct direction reply")
        return frozenset(orig_matchers), frozenset(reply_matchers)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.driver = NetfilterPaceDriver()

        # Remember initialized team interfaces
        self.initialized: set[IfName] = set()

        self.team_class_ids: dict[TeamId, tuple[ClassId, ClassId]] = {}
        # Classes that need to be set up for every team interface
        self.team_interface_classes: dict[
            tuple[ClassId, ClassId], HTBClassTemplate
        ] = {}
        # Optional override for team internal traffic
        self.team_internal_class: HTBClassTemplate | None = None

        # Ip Matchers mapped to their class id
        self.matchers: dict[frozenset[NftMatcher], ClassId] = {}

        # ifname -> manual configuration
        self.manual_tc: dict[str, dict[tuple[ClassId, ClassId], HTBClassTemplate]] = {}

        # Interfaces that should be configured like team interfaces
        self.pseudo_team_interfaces: set[IfName] = set()

        if self.state.network is None:
            return

        cls_id = DEFAULT_CLASS + 2
        if team_tc := self.state.network.team_traffic_control:
            self.team_internal_class = team_tc.internal
            self.team_interface_classes[DEFAULT_CLASSES] = team_tc.default
            teams = sorted(self.state.teams, key=lambda team: team.id)
            for team in teams:
                cls_ids = orig_class_id, reply_class_id = cls_id, cls_id + 1
                orig_matcher, reply_matcher = self._get_team_matchers(team)
                self.matchers[orig_matcher] = orig_class_id
                self.matchers[reply_matcher] = reply_class_id

                self.team_class_ids[team.id] = cls_ids
                self.team_interface_classes[cls_ids] = team_tc.team
                cls_id += 2

        # For non-team ids we decrement from MAX_TC_CLASS_ID, to support dynamically
        # adding teams
        cls_id = MAX_TC_CLASS_ID
        if team_tc and team_tc.net_entities:
            for entity_id, cls_template in team_tc.net_entities.items():
                if (entity := self.state.netEntitiesById.get(entity_id)) is None:
                    LOGGER.warning(f"Unknown net entity in team tc: {entity_id}")
                    continue
                if entity_id in self.local_net_entity_ids:
                    if (iface := entity.interface) is None:
                        LOGGER.warning(
                            f"Net entity {entity_id} should be treated like team, but"
                            " has no interface - tc will only work in one direction"
                        )
                    else:
                        self.pseudo_team_interfaces.add(iface)

                cls_ids = orig_class_id, reply_class_id = cls_id, cls_id - 1
                orig_matcher, reply_matcher = self._get_entitiy_matchers(entity)
                self.matchers[orig_matcher] = orig_class_id
                self.matchers[reply_matcher] = reply_class_id

                # By default, treat entities like an additional teams
                self.team_interface_classes[cls_ids] = cls_template or team_tc.team
                cls_id -= 2

        if team_tc and team_tc.classes:
            for cls in team_tc.classes:
                cls_ids = orig_class_id, reply_class_id = cls_id, cls_id - 1
                orig_matcher, reply_matcher = self._get_class_matchers(cls)
                self.matchers[orig_matcher] = orig_class_id
                self.matchers[reply_matcher] = reply_class_id
                self.team_interface_classes[cls_ids] = cls
                cls_id -= 2

        # We could re-use class ids across interfaces, but since there is 16bits worth
        # of class ids, we can keep it flat - which is better than nested! ;)
        if tc := self.state.network.traffic_control:
            for ifname, if_tc in tc.items():
                classes = {DEFAULT_CLASSES: if_tc.default}
                if if_tc.classes:
                    for cls in if_tc.classes:
                        cls_ids = orig_class_id, reply_class_id = cls_id, cls_id - 1
                        orig_matcher, reply_matcher = self._get_class_matchers(cls)
                        self.matchers[orig_matcher] = orig_class_id
                        self.matchers[reply_matcher] = reply_class_id
                        classes[cls_ids] = cls
                        cls_id -= 2
                self.manual_tc[ifname] = classes

        LOGGER.debug("Team Pseudo Interfaces:")
        LOGGER.debug(pformat(self.pseudo_team_interfaces))
        LOGGER.debug(pformat(self.team_interface_classes))
        LOGGER.debug(pformat(self.matchers))

    async def _command(self, cmd: str, fail_ok: bool = False):
        cmd = cmd.strip()
        LOGGER.debug(f"tc command: {cmd}")
        args = cmd.split(" ")
        proc = await asyncio.create_subprocess_exec(
            "tc", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        await proc.wait()
        if proc.returncode != 0 and not fail_ok:
            raise TCCommandError(
                f'Command "{cmd.strip()}" failed with return code {proc.returncode}\n'
                f"stdout: {stdout.decode()}\n"
                f"stderr: {stderr.decode()}"
            )

    async def configure_interface(
        self,
        ifname: str,
        classes: dict[tuple[ClassId, ClassId], HTBClassTemplate],
    ) -> bool:
        try:
            await self._command(f"qdisc del dev {ifname} root", fail_ok=True)
            await self._command(
                f"qdisc add dev {ifname} root handle 1: htb default {DEFAULT_CLASS:x}"
            )
            for ids, cls in classes.items():
                original_id, reply_id = ids

                original_params = cls.original or cls.params
                reply_params = cls.reply or cls.params

                await self._command(
                    f"class add dev {ifname} root classid 1:{original_id:x} "
                    f"htb {original_params}"
                )
                await self._command(
                    f"class add dev {ifname} root classid 1:{reply_id:x} "
                    f"htb {reply_params}"
                )
                if cls.qdisc:
                    await self._command(
                        f"qdisc add dev {ifname} parent 1:{original_id:x} {cls.qdisc}"
                    )
                    await self._command(
                        f"qdisc add dev {ifname} parent 1:{reply_id:x} {cls.qdisc}"
                    )
        except TCCommandError:
            LOGGER.exception(f"Failed to initialize interface {ifname}")
            return False

        return True

    async def configure_team_interface(self, ifname: str, team_id: str | None = None):
        if ifname in self.initialized:
            LOGGER.debug(f"{ifname} already initialized")
            return

        # Override for "internal" traffic
        effective_classes = self.team_interface_classes.copy()
        if team_id is not None and self.team_internal_class is not None:
            effective_classes[self.team_class_ids[team_id]] = self.team_internal_class

        success = await self.configure_interface(ifname, effective_classes)
        if not success:
            return

        if team_id:
            self.updates.put_nowait(
                InternalUpdate(
                    entity_type=EntityType.Team,
                    entity_id=team_id,
                    update={self.KEYS.INITIALIZED: str(True)},
                )
            )
        else:
            LOGGER.info(f"Configured interface {ifname} like a team interface.")

        self.initialized.add(ifname)

    async def run(self):
        for matchers, class_id in self.matchers.items():
            for net in matchers:
                self.driver.add_class_mapping(net, class_id)

        for ifname in self.pseudo_team_interfaces:
            await self.configure_team_interface(ifname)

        for ifname, classes in self.manual_tc.items():
            await self.configure_interface(ifname, classes)

        return self._yield_all_updates()

    async def team_update(self, team: Team, delete: bool = False):
        if Concierge.KEYS.IFNAME in team.internal_state:
            ifname = team.internal_state[Concierge.KEYS.IFNAME]
            assert ifname is not None
            await self.configure_team_interface(ifname, team_id=team.id)

        elif team.id in self.local_team_ids:
            LOGGER.debug(f"No ifname yet for team {team.id}")
