import re
from abc import ABC, abstractmethod
from argparse import ArgumentParser
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from textwrap import dedent
from typing import Type

from yaml import safe_dump

from ctfroute.adapters.yaml_conf import (
    DefaultsConfig,
    InstanceConfig,
    KubernetesAdapterConfig,
    TeamDefaults,
    YamlConfig,
)
from ctfroute.defs import DEFAULT_MTU, IFNAME_PATTERN
from ctfroute.drivers.netfilter.state import NetfilterAnonymization
from ctfroute.drivers.wireguard.state import (
    WireGuardPeer,
    WireGuardRouterConnectivity,
    WireGuardTeamConnectivity,
)
from ctfroute.scripts.wireguard import HelmValues, fill_wg_keys
from ctfroute.state.external import (
    NET_ENT_MAX_LEN,
    CtfNetwork,
    CtfRouteState,
    HTBClassTemplate,
    NetEntity,
    Router,
    Team,
    TeamTrafficControl,
)

OUTFILE_DEFAULT = Path("./ctfroute.yml")

VULNBOX_IP = 2
GATEWAY_IP = 254
# Entire /24 except:
# - Optional Router (.1)
# - Vulnbox (2.)
# - Infra vantage point (.253)
# - Gateway
# - Broadcast (.255)
MAX_PLAYERS = 255 - 5

# By convention, the infra routers IP in the infra subnet and data plane is ...
ROUTER_INFRA_BASE_IP = GATEWAY_IP
# Doesn't really make sense to have more than one plus a standby ...
MAX_INFRA_ROUTERS = 2
ROUTER_INFRA_MIN_IP = ROUTER_INFRA_BASE_IP - (MAX_INFRA_ROUTERS - 1)

# By convention, worker IPs in the data plane start at ...
WORKER_BASE_IP = 101
MAX_WORKERS = ROUTER_INFRA_MIN_IP - WORKER_BASE_IP + 1

# By convention, router IPs in the data plane start at ...
ROUTER_BASE_IP = 11
MAX_ROUTERS = WORKER_BASE_IP - ROUTER_BASE_IP

# Name of the "infra net" iface of infra routers
INFRA_IFNAME = "infra-net"

# By convention, the infra /24 subnet is ...
INFRA_SUBNET = 251

# Last octet and mask
GAMESERVER_ADDRS = (2, 31)
GAMESERVERS_ENT_NAME = "gameservers"

CHECKER_ADDRS = (16, 26)
CHECKERS_ENT_NAME = "checkers"

# By convention, ...
DATA_PLANE_NET = 232
OVERLAY_NET = 233

# We use 10.232.0.0/24 and upward for overlay and other networks,
# Larger CTFs might want to use a /15
MAX_GAME_BASE = 228

# Used for the router mesh
MESH_BASE_PORT = 40_000

# We could also randomize these
TEAM_BASE_PORT = 50_000

# Fixme: Support > 199 teams with saarctf-style numbering
# We start counting at one
MAX_TEAMS = 200

# Orga team name
ORGA_TEAM = "orga"
# Orga team network range
ORGA_VPN = 250

NOP_TEAM_ID = "1"
NOP_TEAM_NAME = "NOP"

# If a team network is 10.A.B.C, the corresponding cloud net is 10.A+1.B.C
CLOUD_NET_OFFSET = 1 << 16


class TeamIdManager:
    # Reserve three digits for resolving collisions
    max_len = NET_ENT_MAX_LEN - 3

    def __init__(self) -> None:
        self.counter: dict[str, int] = {"": 1}

    @staticmethod
    def normalize(name: str):
        result = ""
        for c in name:
            if IFNAME_PATTERN.match(c):
                result += c

        return result

    def get_id(self, name: str) -> str:
        normalized = self.normalize(name)
        truncated = normalized[: self.max_len]
        count = self.counter.get(truncated, 1)
        assert count < 1000
        if count > 1 or truncated == "":
            result = f"{truncated}{count}"
        else:
            result = truncated
        self.counter[truncated] = count
        return result

    def get_team_cloud_netent(self, team_id: str) -> str:
        return f"cloud-net-{team_id}"


@dataclass
class Context:
    # Numeric base addresses of networks (for easy bit operations)
    network_index: int | None = None
    game_net: int | None = None
    cloud_nets: bool = False
    infra_net: int | None = None
    data_plane_net: int | None = None
    overlay_net: int | None = None
    mesh_port: int | None = None
    teams_initialized: bool = False
    orga_team: Team | None = None
    team_ids: TeamIdManager = TeamIdManager()
    initialState: CtfRouteState = field(
        default_factory=lambda: CtfRouteState(
            network=CtfNetwork(
                mtu=DEFAULT_MTU,
                team_traffic_control=TeamTrafficControl(
                    default=HTBClassTemplate(
                        params="rate 1000mbit prio 0",
                    ),
                    internal=HTBClassTemplate(
                        params="rate 1800mbit prio 0",
                        qdisc="sfq",
                    ),
                    team=HTBClassTemplate(
                        original="rate 20mbit prio 1",
                        reply="rate 20mbit prio 1",
                        qdisc="netem delay 10ms 2ms distribution paretonormal",
                    ),
                ),
            )
        )
    )
    ctf_name: str | None = None
    outfile: Path = OUTFILE_DEFAULT


class Question(ABC):
    question: str
    default: str | None = None

    def skip(self, context: Context) -> bool:
        """
        Should this question be skipped?

        Override in your Question classes.
        """
        return False

    @abstractmethod
    def handle(self, context: Context, answer: str) -> bool: ...


def parse_int_between(answer: str, min: int, max: int) -> int | None:
    error = f"Please enter a number between {min} and {max} (inclusive)"
    if not answer.isnumeric():
        print(error, end="")
        return None

    if (num := int(answer)) not in range(min, max + 1):
        print(error, end="")
        return None

    return num


def parse_bool(answer: str) -> bool | None:
    answer = answer.lower().strip()
    if answer not in ("yes", "no", "n", "y"):
        print("Please enter 'yes' or 'no'", end="")
        return None

    return answer.startswith("y")


class GameNet(Question):
    question = "Which 10.X.0.0/16 do you want to use for the game? X ="

    def handle(self, context: Context, answer: str) -> bool:
        if (num_answer := parse_int_between(answer, 0, MAX_GAME_BASE)) is None:
            return False

        context.network_index = num_answer
        context.game_net = int(IPv4Address(f"10.{num_answer}.0.0"))
        context.infra_net = int(IPv4Address(f"10.{num_answer}.{INFRA_SUBNET}.0"))
        context.data_plane_net = int(IPv4Address(f"10.{DATA_PLANE_NET}.{num_answer}.0"))
        context.overlay_net = int(IPv4Address(f"10.{OVERLAY_NET}.{num_answer}.0"))
        context.mesh_port = MESH_BASE_PORT + num_answer
        return True


class TeamCloudNets(Question):
    question = "Add 10.<X+1>.<TEAM>.0/16 net entities for team cloud networks?"
    default = "yes"

    def handle(self, context: Context, answer: str) -> bool:
        if (do := parse_bool(answer)) is None:
            return False
        elif do:
            context.cloud_nets = do

        return True


class TeamNetData:
    def __init__(self, context: Context) -> None:
        self.context = context

    def for_team(
        self, i: int
    ) -> tuple[IPv4Network, IPv4Network, IPv4Address, IPv4Address, int]:
        assert self.context.game_net is not None
        team_net = self.context.game_net | (i << 8)
        team_cloud_net = team_net + CLOUD_NET_OFFSET
        vulnbox = team_net | VULNBOX_IP
        gateway = team_net | GATEWAY_IP
        return (
            IPv4Network((team_net, 24)),
            IPv4Network((team_cloud_net, 24)),
            IPv4Address(vulnbox),
            IPv4Address(gateway),
            TEAM_BASE_PORT + i,
        )

    def __iter__(self):
        assert self.context.game_net is not None
        for i in range(1, MAX_TEAMS + 1):
            # This should never collide
            assert i != ORGA_VPN
            yield self.for_team(i)


class OrgaVpn(Question):
    question = f"Number of peers in orga vpn (10.X.{ORGA_VPN}.0/24)? 0 to disable"
    default = "20"

    def handle(self, context: Context, answer: str) -> bool:
        assert context.game_net is not None
        if (num := parse_int_between(answer, 0, MAX_PLAYERS)) is None:
            return False
        elif num != 0:
            network, cloud_network, vulnbox, gateway, port = TeamNetData(
                context
            ).for_team(ORGA_VPN)
            peers = [
                WireGuardPeer(
                    allowed_ips=IPv4Network(
                        (context.game_net | (ORGA_VPN << 8) | i, 32)
                    ),
                    public_key="...",
                )
                for i in range(VULNBOX_IP + 1, num + VULNBOX_IP + 1)
            ]

            context.orga_team = Team(
                # Makes sure any other "orga" teams get a different name ;)
                id=context.team_ids.get_id(ORGA_TEAM),
                network=network,
                vulnbox=vulnbox,
                gateway=gateway,
                meta={"name": ORGA_TEAM},
                connectivity=WireGuardTeamConnectivity(
                    public_key="...",
                    private_key="...",
                    port=port,
                    peers=peers,
                ),
            )

        return True


class TeamsFromFile(Question):
    question = (
        "File with one team name per line? Ids remain numeric! Don't forget the "
        "nop-team! Leave empty to specify a number of teams instead"
    )

    def handle(self, context: Context, answer: str) -> bool:
        if answer == "":
            return True

        assert context.initialState.network is not None
        assert context.initialState.network.entities is not None

        path = Path(answer).resolve()
        if not path.is_file():
            print(f"{path} is not a file. ", end="")
            return False

        # Skip empty lines
        lines = [line for line in path.read_text().splitlines() if line]
        if len(lines) > MAX_TEAMS:
            raise ValueError(f"Only up to {MAX_TEAMS} teams supported.")

        for num_id, team_name, net_data in zip(
            range(1, len(lines) + 1), lines, TeamNetData(context)
        ):
            team_id = context.team_ids.get_id(str(num_id))
            cloud_net_entity = context.team_ids.get_team_cloud_netent(team_id)

            network, cloud_network, vulnbox, gateway, port = net_data

            if context.cloud_nets:
                context.initialState.network.entities.append(
                    NetEntity(
                        id=cloud_net_entity,
                        addresses={
                            cloud_network,
                        },
                    )
                )

            context.initialState.teams.append(
                Team(
                    id=team_id,
                    network=network,
                    vulnbox=vulnbox,
                    gateway=gateway,
                    meta={"name": team_name},
                    connectivity=WireGuardTeamConnectivity(
                        public_key="...",
                        private_key="...",
                        port=port,
                        peers=[
                            WireGuardPeer(
                                allowed_ips=IPv4Network((vulnbox, 32)),
                                public_key="...",
                            )
                        ],
                    ),
                )
            )

        context.teams_initialized = True
        return True


class NumberOfTeams(Question):
    question = "How many teams are playing (including NOP)?"

    def skip(self, context: Context) -> bool:
        return context.teams_initialized

    def handle(self, context: Context, answer: str) -> bool:
        if (num_answer := parse_int_between(answer, 0, MAX_TEAMS)) is None:
            return False

        assert context.game_net is not None
        assert context.initialState.network is not None
        assert context.initialState.network.entities is not None

        for i, net_data in zip(range(1, num_answer + 1), TeamNetData(context)):
            network, cloud_network, vulnbox, gateway, port = net_data
            team_name = str(i)
            team_id = context.team_ids.get_id(team_name)
            cloud_net_entity = context.team_ids.get_team_cloud_netent(team_id)
            if team_id == NOP_TEAM_ID:
                team_name = NOP_TEAM_NAME

            if context.cloud_nets:
                context.initialState.network.entities.append(
                    NetEntity(
                        id=cloud_net_entity,
                        addresses={
                            cloud_network,
                        },
                    )
                )

            context.initialState.teams.append(
                Team(
                    id=team_id,
                    meta={"name": team_name},
                    network=network,
                    vulnbox=vulnbox,
                    gateway=gateway,
                    connectivity=WireGuardTeamConnectivity(
                        public_key="...",
                        private_key="...",
                        port=port,
                        peers=[
                            WireGuardPeer(
                                allowed_ips=IPv4Network((vulnbox, 32)),
                                public_key="...",
                            )
                        ],
                    ),
                )
            )
        context.teams_initialized = True
        return True


class NumberOfPlayers(Question):
    question = "How many players per team?"
    default = "40"

    def handle(self, context: Context, answer: str) -> bool:
        if (num_answer := parse_int_between(answer, 0, MAX_PLAYERS)) is None:
            return False

        for team in context.initialState.teams:
            # .1 router, .2 vulnbox
            for i in range(3, num_answer + 3):
                assert team.network is not None
                team_net = int(team.network.network_address)
                player = team_net | i
                team.connectivity.peers.append(
                    WireGuardPeer(
                        allowed_ips=IPv4Network((player, 32)),
                        public_key="...",
                    )
                )
        return True


class CtfName(Question):
    regex = r"[a-z]+[a-z0-9-]*"
    question = f"CTF Name? Must match {regex}"
    error = f"Please specify a name matching {regex}"

    def handle(self, context: Context, answer: str) -> bool:
        if not re.fullmatch(self.regex, answer):
            print(self.error, end="")
            return False
        context.ctf_name = answer
        return True


class NumberOfTeamRouters(Question):
    question = "How many team routers?"
    default = "3"

    def handle(self, context: Context, answer: str) -> bool:
        if (num_answer := parse_int_between(answer, 1, MAX_ROUTERS)) is None:
            return False

        assert context.mesh_port is not None
        assert context.data_plane_net is not None
        assert context.overlay_net is not None
        for i in range(num_answer):
            router_ip = context.data_plane_net | (i + ROUTER_BASE_IP)
            router_overlay_ip = context.overlay_net | (i + ROUTER_BASE_IP)

            teams = {
                team.id
                for idx, team in enumerate(context.initialState.teams)
                if (idx % num_answer) == i
            }
            net_entities = (
                {context.team_ids.get_team_cloud_netent(team) for team in teams}
                if context.cloud_nets
                else set()
            )

            context.initialState.routers.append(
                Router(
                    id=f"{context.ctf_name}-router-{i + 1}",
                    host=str(IPv4Address(router_ip)),
                    teams=teams,
                    net_entities=net_entities,
                    connectivity=WireGuardRouterConnectivity(
                        address=IPv4Address(router_overlay_ip),
                        public_key="...",
                        private_key="...",
                        port=context.mesh_port,
                    ),
                )
            )

        # All teams are assigned to team routers -> Add orga team
        if context.orga_team:
            context.initialState.teams.append(context.orga_team)

        return True


class NumberOfInfraRouters(Question):
    question = "How many infra routers?"
    default = "1"

    def handle(self, context: Context, answer: str) -> bool:
        if (num_answer := parse_int_between(answer, 1, MAX_INFRA_ROUTERS)) is None:
            return False

        assert context.mesh_port is not None
        assert context.data_plane_net is not None
        assert context.overlay_net is not None

        for i in range(num_answer):
            if i == 0 and context.orga_team:
                teams = {context.orga_team.id}
            else:
                teams = set()

            router_ip = context.data_plane_net | (ROUTER_INFRA_BASE_IP - i)
            router_overlay_ip = context.overlay_net | (ROUTER_INFRA_BASE_IP - i)
            context.initialState.routers.append(
                Router(
                    id=f"{context.ctf_name}-router-infra-{i + 1}",
                    teams=teams,
                    host=str(IPv4Address(router_ip)),
                    connectivity=WireGuardRouterConnectivity(
                        address=IPv4Address(router_overlay_ip),
                        public_key="...",
                        private_key="...",
                        port=context.mesh_port,
                    ),
                )
            )
        return True


class NumberOfWorkers(Question):
    question = "How many workers?"
    default = "3"

    def handle(self, context: Context, answer: str) -> bool:
        if (num_answer := parse_int_between(answer, 0, MAX_WORKERS)) is None:
            return False

        assert context.mesh_port is not None
        assert context.data_plane_net is not None
        assert context.overlay_net is not None

        for i in range(num_answer):
            router_ip = context.data_plane_net | (i + WORKER_BASE_IP)
            router_overlay_ip = context.overlay_net | (i + WORKER_BASE_IP)
            context.initialState.routers.append(
                Router(
                    id=f"{context.ctf_name}-worker-{i + 1}",
                    host=str(IPv4Address(router_ip)),
                    connectivity=WireGuardRouterConnectivity(
                        address=IPv4Address(router_overlay_ip),
                        public_key="...",
                        private_key="...",
                        port=context.mesh_port,
                    ),
                )
            )

        return True


class AddInfraNetEntites(Question):
    question = "Add checker & gameserver net entities to first infra router? yes / no"
    default = "yes"

    def handle(self, context: Context, answer: str) -> bool:
        if (do := parse_bool(answer)) is None:
            return False

        elif do:
            assert context.infra_net is not None
            assert context.initialState.network is not None
            assert context.initialState.network.entities is not None

            offset, mask = GAMESERVER_ADDRS
            gameservers_net = IPv4Network((context.infra_net | offset, mask))
            offset, mask = CHECKER_ADDRS
            checkers_net = IPv4Network((context.infra_net | offset, mask))
            context.initialState.network.entities += [
                NetEntity(
                    id=GAMESERVERS_ENT_NAME,
                    addresses={gameservers_net},
                    interface=INFRA_IFNAME,
                ),
                NetEntity(
                    id=CHECKERS_ENT_NAME,
                    addresses={checkers_net},
                    interface=INFRA_IFNAME,
                ),
            ]
            infra_router_1 = [
                router
                for router in context.initialState.routers
                if router.id.endswith("router-infra-1")
            ][0]
            infra_router_1.net_entities = {GAMESERVERS_ENT_NAME, CHECKERS_ENT_NAME}

            assert context.initialState.network.team_traffic_control is not None
            context.initialState.network.team_traffic_control.net_entities = {
                CHECKERS_ENT_NAME: None,  # Will be treated like a team
                GAMESERVERS_ENT_NAME: HTBClassTemplate(
                    params="rate 50mbit prio 0",
                    qdisc="sfq",
                ),
            }

        return True


class RollWireGuardKeys(Question):
    question = "Roll wireguard keys? yes / no"
    default = "yes"

    def handle(self, context: Context, answer: str) -> bool:
        if (do := parse_bool(answer)) is None:
            return False
        elif do:
            fill_wg_keys(context.initialState)

        return True


class Outfile(Question):
    question = "Output file?"
    default = str(OUTFILE_DEFAULT)

    def handle(self, context: Context, answer: str) -> bool:
        path = Path(answer).resolve()
        if not path.parent.is_dir():
            print(f"{path.parent} is not a directory!", end="")
            return False
        context.outfile = path
        return True


steps: list[Type[Question]] = [
    GameNet,
    TeamCloudNets,
    TeamsFromFile,
    NumberOfTeams,
    NumberOfPlayers,
    OrgaVpn,
    CtfName,
    NumberOfTeamRouters,
    NumberOfInfraRouters,
    NumberOfWorkers,
    AddInfraNetEntites,
    RollWireGuardKeys,
    Outfile,
]


def cli_main():
    parser = ArgumentParser(description="""Interactively prepare your ctfroute.yml.""")
    parser.add_argument(
        "-c",
        "--chart",
        action="store_true",
        help="Generate chart values instead of ctfroute config.",
    )
    # TODO support flags instead of interactive?
    args = parser.parse_args()

    context = Context()

    print(
        dedent("""
    Let's get your ctfroute configured.
    You can hit return to accept the default value if one is shown!
    """)
    )

    for Step in steps:
        step = Step()
        if step.skip(context):
            continue
        prompt = step.question + " "
        if step.default:
            prompt += f"Default: {step.default} "

        answer = input(prompt)
        if answer.strip() == "" and step.default:
            answer = step.default
        success = step.handle(context, answer)
        while not success:
            answer = input(" ")
            # No more default handling if you entered something wrong!
            success = step.handle(context, answer)

    assert context.outfile is not None

    config: YamlConfig | HelmValues
    config = YamlConfig(adapters=[], initial_state=context.initialState)

    config.defaults = DefaultsConfig(
        teams=TeamDefaults(anonymization=NetfilterAnonymization())
    )

    if args.chart:
        assert context.ctf_name is not None
        assert context.network_index is not None
        config.adapters = [KubernetesAdapterConfig(namespace=context.ctf_name)]
        config.instance = InstanceConfig(metrics=Path("/var/ctfroute/metrics/metrics"))
        config = HelmValues(
            ctf=context.ctf_name,
            network_index=context.network_index,
            ctfroute=config,
        )

    context.outfile.write_text(
        safe_dump(config.model_dump(mode="json", by_alias=True), indent=2)
    )
    print(
        dedent(f"""
    Done, config file written to: {context.outfile}
    Enjoy your game!
    """)
    )
