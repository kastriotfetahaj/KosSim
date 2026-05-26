__all__ = [
    "GateHandle",
    "NFTError",
    "NetfilterAnonymizationDriver",
    "NetfilterPaceDriver",
    "NftablesDriver",
]

import json
from abc import ABC
from json import JSONDecodeError
from logging import getLogger
from textwrap import dedent
from typing import Any, Literal, NamedTuple, assert_never, cast, get_args

from ctfroute.defs import MSS_DIFF, NFTSetPrefix
from ctfroute.drivers.base import AnonymizationDriver, AnonymizationHandle
from ctfroute.drivers.exceptions import BadState, InsufficientState
from ctfroute.drivers.netfilter.nftables import Nftables
from ctfroute.exceptions import CtfRouteException
from ctfroute.state.external import (
    GateType,
    NetEntity,
    NetRef,
    NetRefKeyword,
    NetRefPrefix,
    Period,
)
from ctfroute.state.internal import ConnGate, Gate, Team
from ctfroute.utils import NFT_LOGGER_NAME

NFT_MAX_COMMENT = 128
LOGGER = getLogger(__name__)


class NFTError(CtfRouteException):
    """Something went wrong while performing to nftables commands."""

    def __init__(
        self, msg: str, *, code: int | None = None, out: str | list | None = None
    ):
        super().__init__(msg)
        self.code = code
        self.out = out

    def __str__(self) -> str:
        return f"NFT Code: {self.code} Message:\n{self.msg}\nOutput:\n{self.out}"


_NFT: Nftables | None = None


class NftBasedDriver(ABC):
    nft_logger = getLogger(NFT_LOGGER_NAME)

    @property
    def nft(self) -> Nftables:
        global _NFT

        if _NFT is None:
            _NFT = Nftables()
            _NFT.set_json_output(True)
            _NFT.set_handle_output(True)
            _NFT.set_echo_output(True)

        return _NFT

    def cmd(self, command: str) -> list[dict[str, Any]]:
        """
        Perform str commands but get JSON output.

        Nftables has cmd and json_cmd, but they take AND return str / dict respectively.
        We typically want to input str but handle the result as dict.
        """
        command = dedent(command)
        self.nft_logger.debug(command)

        code, out_str, err = self.nft.cmd(command)

        if code != 0:
            LOGGER.error(
                f"nft command failed with code: {code}\n{err}\n"
                f"out:\n{out_str}\ncommand:\n{command}"
            )
            raise NFTError(err, code=code, out=out_str)

        if not out_str:
            return []

        try:
            out = json.loads(out_str)
            return out["nftables"]
        except JSONDecodeError as e:
            LOGGER.error("Failed to decode nft output", exc_info=e)
            raise NFTError("Failed to decode nft output", code=code, out=out_str) from e
        except KeyError as e:
            LOGGER.error("nft output contained no 'nftables' key.", exc_info=e)
            raise NFTError(
                "nft output contained no 'nftables' key.", code=code, out=out_str
            )


class AnonDriverState(NamedTuple):
    rules: set[tuple[str, int]]


class NetfilterAnonymizationDriver(
    AnonymizationDriver[AnonDriverState], NftBasedDriver
):
    name = "netfilter"

    TABLE = "ctfr-anon"
    CHAIN_NAT = "nat"
    MANGLE_ALL = "mangle-all"
    CHAIN_MANGLE_EGRESS = "mangle-egress"
    CHAIN_PREROUTING = "prerouting"
    SAME_TEAM = "same-team"
    REMOTE_TEAMS = "remote-teams"
    LOCAL_TEAMS = "local-teams"

    def __init__(self, *, mtu: int):
        """
        Initialize the driver.

        This prepares the tables and chains. It should be called when the cleaner
        is initialized.
        """
        super().__init__(mtu=mtu)
        self.mss = mtu - MSS_DIFF
        # Team internal traffic bypasses all this processing for simplicity.

        # It seems to be common practice on backbone networks to prohibit packets that
        # have ip options set, i.e. hdrlength != 5. So we just do that as well.

        # To prevent pmtu fingerprinting and other shenanigans we drop icmp traffic on
        # the ingress routers of teams, except for:
        # echo request, reply and host unreachable messages with the regular codes:
        # 0: Net unreachable
        # 1: Host unreachable
        # 2: Proto unreachable
        # 3: Port Unreachable
        # 10: Host administratively prohibited
        # 13: Communication administratively prohibited

        # We keep the TTL above 1 for remote teams so router topology can not be
        # tracerouted. For team traffic between routers we can be confident that there
        # are no routing loops. Between the router and team-controlled peers or other
        # stuff running on the host we can't be that sure.

        # We cap the TTL at 32, So there is ample room for hops between the vpn
        # entrypoint and checkers / players / exploiters without them being
        # fingerprintable based on ttl.

        # Packets with invalid ct state are dropped.
        self.cmd(f"""\
            add table ip {self.TABLE}
            delete table {self.TABLE} 
            add table ip {self.TABLE} {{
                set {self.LOCAL_TEAMS} {{ type ipv4_addr; flags interval; }}
                set {self.REMOTE_TEAMS} {{ type ipv4_addr; flags interval; }}
                set {self.SAME_TEAM} {{ typeof ip saddr . ip daddr; flags interval; }} 
                chain {self.MANGLE_ALL} {{
                    ip dscp set 0;
                    ip ecn set 0;  
                    reset tcp option timestamp;
                    reset tcp option window;
                    reset tcp option sack-perm;
                    reset tcp option sack;
                    reset tcp option sack0;
                    reset tcp option sack1;
                    reset tcp option sack2;
                    reset tcp option sack3;
                    reset tcp option md5sig;
                    reset tcp option eol;
                    tcp flags syn tcp option maxseg size set {self.mss};
                }}
                
                chain {self.CHAIN_MANGLE_EGRESS} {{
                    ip ttl > 32 ip ttl set 32;
                }}
                 
                chain {self.CHAIN_PREROUTING} {{
                    type filter hook prerouting priority filter; policy accept;
                    ip saddr . ip daddr @{self.SAME_TEAM} accept;
                    ip saddr @{self.LOCAL_TEAMS} ip hdrlength != 5 reject with icmp type admin-prohibited;  
                    ip saddr @{self.LOCAL_TEAMS} icmp type != {{ 0, 3, 8 }} drop;
                    ip saddr @{self.LOCAL_TEAMS} icmp type 3 icmp code != {{ 0, 1, 2, 3, 10, 13 }} drop;   
                    ip saddr @{self.LOCAL_TEAMS} jump {self.MANGLE_ALL};
                    ip daddr @{self.LOCAL_TEAMS} jump {self.MANGLE_ALL};
                    ip daddr @{self.REMOTE_TEAMS} ip ttl 1 ip ttl set 2;
                    ip daddr @{self.LOCAL_TEAMS} jump {self.CHAIN_MANGLE_EGRESS}; 
                    ct state invalid counter drop;
                }}
                
                chain {self.CHAIN_NAT} {{
                    type nat hook postrouting priority srcnat; policy accept;
                }}
            }}
            """)

    async def set_up(
        self, team: Team, anonymize: bool
    ) -> AnonymizationHandle[AnonDriverState]:
        if team.network is None or team.gateway is None:
            raise InsufficientState(f"Team {team.id} lacks a network or gateway.")

        rules = set()
        self.cmd(
            f"add element {self.TABLE} {self.SAME_TEAM} {{ {team.network} . {team.network} }}"
        )

        if anonymize:
            out = self.cmd(f"""\
                add rule {self.TABLE} {self.CHAIN_NAT} ip daddr {team.network} ip saddr != {team.network} snat to {team.gateway};
                add element {self.TABLE} {self.LOCAL_TEAMS} {{ {team.network} }}
                """)

            try:
                for info in out:
                    # Kernel differences in nft ?
                    if "add" in info:
                        add_info = info["add"]
                    elif "insert" in info:
                        add_info = info["insert"]
                    else:
                        raise KeyError("add/insert")

                    if "element" in add_info:
                        continue
                    elif "rule" in add_info:
                        rule_info = add_info["rule"]
                    else:
                        raise KeyError("rule")

                    rules.add((rule_info["chain"], rule_info["handle"]))
            except KeyError:
                raise NFTError(
                    "Couldn't get rule handle after inserting NAT rule.", out=out
                )
        else:
            self.cmd(f"add element {self.TABLE} remote-teams {{ {team.network} }}")

        handle = AnonymizationHandle(
            team=team.model_copy(),
            anonymized=anonymize,
            driver_state=AnonDriverState(rules=rules),
            driver=self,
        )

        return handle

    async def tear_down(self, handle: AnonymizationHandle[AnonDriverState]) -> None:
        network = handle.team.network
        cmd = f"delete element {self.TABLE} {self.SAME_TEAM} {{ {network} . {network} }}\n"
        if handle.anonymized:
            cmd += f"delete element {self.TABLE} {self.LOCAL_TEAMS} {{ {network} }}\n"
            for chain, nft_handle in handle.driver_state.rules:
                cmd += f"delete rule {self.TABLE} {chain} handle {nft_handle}\n"
        else:
            cmd += f"delete element {self.TABLE} {self.REMOTE_TEAMS} {{ {network} }}\n"
        self.cmd(cmd)


class NetfilterPaceDriver(NftBasedDriver):
    TABLE = "ctfr-pace"
    CHAIN_CLASSIFY = "classify"
    PRIO_MAP = "team"

    def __init__(self):
        self.cmd(f"""\
            add table ip {self.TABLE}
            delete table ip {self.TABLE}
            add table ip {self.TABLE} {{ 
                chain {self.CHAIN_CLASSIFY} {{
                    type filter hook postrouting priority filter + 1; policy accept;        
                    counter;  
                }}
            }}
            """)

    def add_class_mapping(self, matcher: str, class_id: int):
        self.cmd(
            f"insert rule {self.TABLE} {self.CHAIN_CLASSIFY} {matcher} meta priority set 1:{class_id:x} counter accept;"
        )


# Type to enumerate all possible "kinds" of NetRef
# This is primarily used for exhaustiveness checking
NetRefKind = NetRefKeyword | NetRefPrefix

# All types of NetRefKinds that are compatible with other-team & same-team
# This is primarily used for exhaustiveness checking
NetRefCompatSameOther = Literal[
    NetRefKeyword.any_vulnbox,
    NetRefKeyword.any_team,
    NetRefPrefix.team,
    NetRefPrefix.vulnbox,
]

# Used for error messages
NetRefCompatSameOtherStr = ", ".join(get_args(NetRefCompatSameOther))


# Gatekeeper must maintain a mapping between enforced gates and the nft handles of
# corresponding rules to perform updates and deletions. Maintaining this mapping is
# simpler and more performant than trying to map gates to rules using comments or
# other guesswork. It comes at the "cost" of having to flush and recreate gates when
# ctfroute is restarted / crashes, but that shouldn't™️ happen in the first place.
# As of writing all gates can be implemented with a single rule, but that might change,
# so we are making this a set of ints instead of a single int.
GateHandle = set[int]


# This driver deviates a little bit from the usual pattern, because there aren't any
# plans to provide alternative driver for gates / firewalling. Note that even if you
# think you are still using iptables instead of nft, you are likely just using the
# nft wrapper that translates from the old iptables syntax to nft. :)
class NftablesDriver(NftBasedDriver):
    TABLE = "ctfr-gates"
    CHAIN = "gates"

    META_SETS = (
        NetRefKeyword.known,
        NetRefKeyword.any_team,
        NetRefKeyword.any_vulnbox,
        NetRefKeyword.same_team,
    )

    def setup(self):
        """
        Prepare tables, chains and sets used by this driver.

        Note that the chain holding gates gets flushed!
        TODO: Not atomic!
        """
        self.cmd(f"""\
            add table {self.TABLE}
            add chain {self.TABLE} {self.CHAIN} {{ type filter hook forward priority filter; }}
            flush chain {self.TABLE} {self.CHAIN}
 
            add set {self.TABLE} {NetRefKeyword.same_team} {{ typeof ip saddr . ip daddr; flags interval; }}
            """)

        # these all have the same type
        for name in (
            NetRefKeyword.known,
            NetRefKeyword.any_team,
            NetRefKeyword.any_vulnbox,
        ):
            self.cmd(f"""\
                add set {self.TABLE} {name} {{ type ipv4_addr; flags interval; }}
                flush set {self.TABLE} {name}
                """)

    def set_entity(self, entity: NetEntity | Team):
        """
        Create / update set representing an entity (NetEntity or Team).

        id attributes are mapped to set names. Note that having entities set up is
        prerequisite to deploying gates that reference these entities.
        TODO: Not atomic !
        """
        if isinstance(entity, NetEntity):
            set_name = self._get_set_prefix(NetRefPrefix.game) + entity.id
            self.cmd(f"""\
                add set {self.TABLE} {set_name} {{ type ipv4_addr; flags interval; }}
                flush set {self.TABLE} {set_name}
                """)

            if entity.addresses:
                addresses = ", ".join(str(addr) for addr in entity.addresses)
                self.cmd(f"""\
                    add element {self.TABLE} {set_name} {{ {addresses} }} 
                    add element {self.TABLE} {NetRefKeyword.known} {{ {addresses} }}               
                    """)

        elif isinstance(entity, Team):
            set_name = self._get_set_prefix(NetRefPrefix.team) + entity.id
            self.cmd(f"""\
                add set {self.TABLE} {set_name} {{ type ipv4_addr; flags interval; }}
                flush set {self.TABLE} {set_name}
                """)

            if entity.network:
                self.cmd(f"""\
                    add element {self.TABLE} {set_name} {{ {entity.network} }}
                    add element {self.TABLE} {NetRefKeyword.known} {{ {entity.network} }}
                    add element {self.TABLE} {NetRefKeyword.any_team} {{ {entity.network} }}               
                    add element {self.TABLE} {NetRefKeyword.same_team} {{ {entity.network} . {entity.network} }}               
                    """)

            if entity.vulnbox:
                self.cmd(f"""\
                    add element {self.TABLE} {NetRefKeyword.any_vulnbox} {{ {entity.vulnbox} }}
                    """)
        else:
            assert_never(entity)

    def delete_entity(self, entity: NetEntity | Team):
        """
        Delete set representing an entity (NetEntity or Team).

        You cannot delete entities if there are any gates still referencing them.
        TODO: Not atomic!
        """
        if isinstance(entity, NetEntity):
            set_name = self._get_set_prefix(NetRefPrefix.game) + entity.id
            self.cmd(f"delete set {self.TABLE} {set_name}")
            if entity.addresses:
                addresses = ", ".join(str(addr) for addr in entity.addresses)
                self.cmd(
                    f"delete element {self.TABLE} {NetRefKeyword.known} {{ {addresses} }}"
                )

        elif isinstance(entity, Team):
            set_name = self._get_set_prefix(NetRefPrefix.team) + entity.id
            self.cmd(f"delete set {self.TABLE} {set_name}")

            if entity.network:
                self.cmd(f"""\
                    delete element {self.TABLE} {NetRefKeyword.known} {{ {entity.network} }}               
                    delete element {self.TABLE} {NetRefKeyword.any_team} {{ {entity.network} }}               
                    delete element {self.TABLE} {NetRefKeyword.same_team} {{ {entity.network} . {entity.network} }}               
                    """)
            if entity.vulnbox:
                self.cmd(f"""\
                    delete element {self.TABLE} {NetRefKeyword.any_vulnbox} {{ {entity.vulnbox} }}
                    """)
        else:
            assert_never(entity)

    def set_gate(self, gate: Gate, handles: GateHandle | None = None) -> GateHandle:
        """
        Create / update a gate.

        To set an existing gate, pass the handles that where returned when it was last
        set. Updates are implemented as a replacement of rules, so you will get new
        handles returned when performing an update and need to store them!
        """
        rules = []
        if gate.type == GateType.raw:
            rules = [gate.rule]
        elif gate.type == GateType.connection:
            rules = self._render_conn_gate(gate)
        else:
            assert_never(gate.type)

        return self._set_rules_from_expressions(rules, handles)

    def delete_gate(self, handle: GateHandle) -> None:
        """Delete a gate."""
        cmd = "\n".join(self._get_delete_rule_cmds(handle))
        self.cmd(cmd)

    @staticmethod
    def _get_net_ref_kind(conn_endpoint: str) -> NetRefKind:
        for kw in NetRefKeyword:
            if kw == conn_endpoint:
                return kw
        for pf in NetRefPrefix:
            if conn_endpoint.startswith(pf):
                return pf
        raise ValueError(f"{conn_endpoint} is not a valid net reference")

    @staticmethod
    def _get_set_prefix(ref_prefix: NetRefPrefix) -> str:
        """Get the nft set name prefix for a NetRefPrefix."""
        match ref_prefix:
            case NetRefPrefix.team:
                return NFTSetPrefix.team
            case NetRefPrefix.game:
                return NFTSetPrefix.game
            case NetRefPrefix.vulnbox:
                raise ValueError("We don't create sets for vulnboxes.")
            case _:
                assert_never(NetRefPrefix)

    @staticmethod
    def _get_entity_id(id: NetRef, prefix: NetRefPrefix) -> str:
        """
        Get the id of an entity from a NetEntityRef without its prefix.

        Also assert that the correct prefix was passed.
        """
        assert id.startswith(prefix)
        return id.lstrip(prefix)

    @classmethod
    def _get_set_name(cls, id: NetRef, kind: NetRefPrefix) -> str:
        """Get the nft set name for a prefixed NetEntityRef."""
        return cls._get_set_prefix(kind) + cls._get_entity_id(id, kind)

    @staticmethod
    def _comment_conn_gate(gate: ConnGate) -> str:
        full = f"ConnGate src: {gate.conn_src} dst: {gate.conn_dst} id: {gate.id}"
        if len(full) > NFT_MAX_COMMENT:
            full = full[: NFT_MAX_COMMENT - 3] + "..."
        return full

    @staticmethod
    def _render_period(period: Period) -> str:
        time_expression = ""
        if period.from_time:
            time_expression += f"time > {int(period.from_time.timestamp())} "
        if period.to_time:
            time_expression += f"time < {int(period.to_time.timestamp())} "
        return time_expression

    @classmethod
    def _render_conn_gate(cls, gate: ConnGate) -> list[str]:
        """Render the nft rule(s) to implement a ConnGate."""
        conn_src, conn_dst = gate.conn_src, gate.conn_dst
        src_kind = cls._get_net_ref_kind(conn_src) if conn_src else None
        dst_kind = cls._get_net_ref_kind(conn_dst) if conn_dst else None

        src_match: str | None = None
        dst_match: str | None = None

        match src_kind:
            case None:
                src_match = ""
            case (
                NetRefKeyword.known | NetRefKeyword.any_team | NetRefKeyword.any_vulnbox
            ):
                src_match = f"ip saddr @{src_kind}"
            case NetRefKeyword.unknown:
                src_match = "ip saddr != @known"
            case NetRefKeyword.same_team:
                raise BadState(f"{src_kind} may not be used for connSrc, only connDst.")
            case NetRefKeyword.other_team:
                if dst_kind not in get_args(NetRefCompatSameOther):
                    raise BadState(
                        f"{src_kind} must be used with: {NetRefCompatSameOtherStr}"
                    )
                src_match = "ip saddr . ip daddr != @same-team"
            case NetRefPrefix.vulnbox:
                assert conn_src is not None
                id = cls._get_entity_id(conn_src, src_kind)
                team_set_name = cls._get_set_prefix(NetRefPrefix.team) + id
                src_match = f"ip saddr @{team_set_name} ip saddr @any-vulnbox"
            case NetRefPrefix.team | NetRefPrefix.game:
                assert conn_src is not None
                set_name = cls._get_set_name(conn_src, src_kind)
                src_match = f"ip saddr @{set_name}"
            case _:
                assert_never(NetRefKind | None)

        assert src_match is not None

        match dst_kind:
            case None:
                dst_match = ""
            case (
                NetRefKeyword.known | NetRefKeyword.any_team | NetRefKeyword.any_vulnbox
            ):
                dst_match = f"ip daddr @{dst_kind}"
            case NetRefKeyword.unknown:
                dst_match = "ip daddr != @known"
            case NetRefKeyword.same_team:
                if src_kind not in get_args(NetRefCompatSameOther):
                    raise BadState(
                        f"{dst_kind} must be used with {NetRefCompatSameOtherStr}"
                    )
                src_kind = cast(NetRefCompatSameOther, src_kind)
                conn_src = cast(str, conn_src)
                match src_kind:
                    case NetRefKeyword.any_vulnbox | NetRefKeyword.any_team:
                        dst_match = "ip saddr . ip daddr @same-team"
                    case NetRefPrefix.team | NetRefPrefix.vulnbox:
                        id = cls._get_entity_id(conn_src, src_kind)
                        set_name = cls._get_set_prefix(NetRefPrefix.team) + id
                        dst_match = f"ip daddr @{set_name}"
                    case _:
                        assert_never(NetRefCompatSameOther)
            case NetRefKeyword.other_team:
                if src_kind not in get_args(NetRefCompatSameOther):
                    raise BadState(
                        f"{dst_kind} must be used with {NetRefCompatSameOtherStr}"
                    )
                dst_match = "ip saddr . ip daddr != @same-team"
            case NetRefPrefix.vulnbox:
                assert conn_dst is not None
                id = cls._get_entity_id(conn_dst, dst_kind)
                team_set_name = cls._get_set_prefix(NetRefPrefix.team) + id
                dst_match = f"ip daddr @{team_set_name} ip daddr @any-vulnbox"
            case NetRefPrefix.team | NetRefPrefix.game:
                conn_dst = cast(str, conn_dst)
                set_name = cls._get_set_name(conn_dst, dst_kind)
                dst_match = f"ip daddr @{set_name}"
            case _:
                assert_never(NetRefKind | None)

        time_expression = cls._render_period(gate.period) if gate.period else ""
        return [
            f"{src_match} {dst_match} {gate.expression or ''} "
            f"ct direction original {time_expression}"
            f'counter drop comment "{cls._comment_conn_gate(gate)}"'
        ]

    @classmethod
    def _get_delete_rule_cmds(cls, handle: GateHandle) -> list[str]:
        return [
            f"delete rule {cls.TABLE} {cls.CHAIN} handle {nft_handle}"
            for nft_handle in handle
        ]

    @classmethod
    def _get_add_rule_cmds(cls, expressions: list[str]):
        return [
            f"add rule {cls.TABLE} {cls.CHAIN} {expression}"
            for expression in expressions
        ]

    def _set_rules_from_expressions(
        self, expressions: list[str], handles: GateHandle | None = None
    ) -> GateHandle:
        """
        Sets rules representing a gate atomically.

        Passed nft handles are deleted and new ones are returned.
        """
        cmds = []
        if handles:
            cmds += self._get_delete_rule_cmds(handles)
        cmds += self._get_add_rule_cmds(expressions)

        cmd = "\n".join(cmds)
        out = self.cmd(cmd)

        assert len(expressions) == len(out)

        new_handles: set[int] = set()
        try:
            echo: dict
            for echo in out:
                new_handles.add(cast(int, echo["add"]["rule"]["handle"]))
        except KeyError:
            raise NFTError(
                "No handle found in add rule output.",
                out=out,
                code=0,
            )
        return new_handles
