import subprocess
from argparse import ArgumentParser
from pathlib import Path

from yaml import safe_dump, safe_load

from ctfroute.adapters.yaml_conf import YamlConfig, validate_yaml_conf
from ctfroute.drivers.wireguard.state import (
    WireGuardPeer,
    WireGuardRouterConnectivity,
    WireGuardTeamConnectivity,
)
from ctfroute.scripts.utils import HelmValues
from ctfroute.state.external import CtfRouteState


def run_subprocess(args: list[str], input: str | None = None) -> bytes:
    if input:
        bytes_input = input.encode()
    else:
        bytes_input = None
    result = subprocess.run(
        args, stderr=subprocess.PIPE, stdout=subprocess.PIPE, input=bytes_input
    )
    if result.returncode != 0:
        raise Exception(f"{args} returned {result.returncode}")
    return result.stdout


def exec_wg_priv() -> str:
    return run_subprocess(["wg", "genkey"]).strip().decode()


def exec_wg_pub(priv: str) -> str:
    return run_subprocess(["wg", "pubkey"], input=priv).strip().decode()


def fill_wg_peers(peers: list[WireGuardPeer]):
    for peer in peers:
        private_key = exec_wg_priv()
        public_key = exec_wg_pub(private_key)
        peer.private_key = private_key
        peer.public_key = public_key


def fill_wg_keys(config: CtfRouteState):
    for team in config.teams:
        if isinstance(team.connectivity, WireGuardTeamConnectivity):
            private_key = exec_wg_priv()
            public_key = exec_wg_pub(private_key)
            team.connectivity.private_key = private_key
            team.connectivity.public_key = public_key
            fill_wg_peers(team.connectivity.peers)

    for router in config.routers:
        if isinstance(router.connectivity, WireGuardRouterConnectivity):
            private_key = exec_wg_priv()
            public_key = exec_wg_pub(private_key)
            router.connectivity.private_key = private_key
            router.connectivity.public_key = public_key


def cli_main():
    parser = ArgumentParser(
        description="""
        Roll new wireguard keys for your existing ctfroute configuration.
        You can specify a ctfroute config or any yaml file containing a valid config
        under the key "ctfroute" (e.g. helmchart-values). 
        """
    )
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        help="output file, result is printed to stdout if this flag is omitted",
    )
    args = parser.parse_args()

    raw_config_path: Path = args.input
    out_config_path: Path | None = args.out

    config_yaml_raw = safe_load(raw_config_path.read_text())
    helm_config: HelmValues | None = None
    ctfroute_config: YamlConfig

    if "ctfroute" in config_yaml_raw:
        helm_config = HelmValues.model_validate(config_yaml_raw)
        ctfroute_config = helm_config.ctfroute
    else:
        ctfroute_config = YamlConfig.model_validate(config_yaml_raw)

    validate_yaml_conf(ctfroute_config, write_defaults=False)
    fill_wg_keys(ctfroute_config.initial_state)

    if helm_config is not None:
        config_out_data = safe_dump(
            helm_config.model_dump(mode="json", exclude_none=True, by_alias=True),
            indent=2,
        )
    else:
        config_out_data = safe_dump(
            ctfroute_config.model_dump(mode="json", exclude_none=True, by_alias=True),
            indent=2,
        )

    if out_config_path is not None:
        out_config_path.write_text(config_out_data)
    else:
        print(config_out_data)
