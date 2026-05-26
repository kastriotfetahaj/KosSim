import logging
from pathlib import Path
from random import Random, SystemRandom
from random import seed as seed_random

import pytest
from fastapi.testclient import TestClient
from pytest import Config, fixture

from ctfroute import debug, utils
from ctfroute.adapters.yaml_conf import (
    KubernetesAdapterConfig,
    YamlConfig,
    read_yaml_conf,
)
from ctfroute.controllers import GateKeeper
from ctfroute.drivers.netfilter.nftables import Nftables
from ctfroute.state import LocalContext
from ctfroute.state.internal import CtfRouteState
from ctftest.agent.client import VulnboxesClient
from ctftest.test_rest_server import app as rest_server

DOCKER_CONF_PATH = Path(__file__).parent / "../../docker/ctfroute.yml"
LOCAL_CONF_PATH = Path(__file__).parent / "./router1_ctfroute.yml"
K8S_CONF_PATH = Path(__file__).parent / "../../docker/kubernetes.ctfroute.yml"
LOGGER = logging.getLogger(__name__)


def pytest_addoption(parser):
    """Add options to pytest cli."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests, nothing else.",
    )
    parser.addoption(
        "--preflight",
        action="store_true",
        default=False,
        help="Run pre flight tests, nothing else",
    )
    # use '=' to pass the filepath (space separation does not work)
    parser.addoption(
        "--ctfroute-config",
        type=Path,
        help="Path to the ctfroute config file",
    )
    parser.addoption(
        "--kubernetes",
        action="store_true",
        default=False,
        help="Run tests needing kubernetes",
    )
    parser.addoption(
        "--k8s-namespace",
        type=str,
        help="Namespace used to store gates, implies --kubernetes",
    )
    parser.addoption(
        "--no-namespace",
        action="store_true",
        default=False,
        help="Run unit tests without unshare",
    )
    parser.addoption(
        "--seed", default=0, type=int, help="PRNG seed for unit tests (0: random)"
    )
    parser.addoption(
        "--max-vulnboxes",
        type=int,
        help="Limit Number of vulnboxes for preflight checks",
    )


def pytest_collection_modifyitems(config, items):
    """
    Modify test marks.

    Specifically either skip all integration tests or all tests not marked as
    integration tests. This is done because integration tests talk to the vulnboxes
    running in docker, thus they need access to the host network namespace. Some of the
    non-integration tests however require dropping into a namespace in order to not
    screw up the host network namespace. (See enter_namespace fixture).
    """
    integration = config.getoption("--integration")
    preflight = config.getoption("--preflight")
    kubernetes = config.getoption("--kubernetes") or config.getoption("--k8s-namespace")

    assert not (integration and preflight)

    skip_k8s = pytest.mark.skip(reason="Need --kubernetes option to run")
    skip_integration = pytest.mark.skip(reason="Need --integration option to run")
    skip_unit = pytest.mark.skip(
        reason="Skipped because integration or preflight test are run"
    )
    skip_pre_flight = pytest.mark.skip(reason="Need --preflight option to run")

    for item in items:
        if not kubernetes and "kubernetes" in item.keywords:
            item.add_marker(skip_k8s)

        if "integration" in item.keywords:
            if not integration:
                item.add_marker(skip_integration)
        elif "preflight" in item.keywords:
            if not preflight:
                item.add_marker(skip_pre_flight)
        elif integration or preflight:
            item.add_marker(skip_unit)


@fixture(scope="session", autouse=True)
def setup_logging() -> None:
    utils.setup_logging()


@fixture(scope="session")
def random(pytestconfig: Config) -> Random:
    """Return seeded random and log seed for reproducibility."""
    if (seed := pytestconfig.getoption("--seed")) == 0:
        seed = SystemRandom().randint(0, 1 << 64)
    LOGGER.debug(f"Test random seed: {seed}")
    return Random(seed)


@fixture(scope="session")
def seed(random: Random) -> None:
    """Seeds the default random number generator."""
    seed_random(random.randint(0, 1 << 64))


@fixture(scope="function")
def rand_ent_id(random: Random) -> str:
    """Random id as used for teams and such."""
    return str(random.randint(0, 1000))


@fixture(scope="package")
def configs_dir() -> Path:
    return Path(__file__).parent / "test-configs"


@fixture(scope="session")
def maybe_enter_namespace(pytestconfig: Config) -> None:
    """Expose utils.enter_namespace as a fixture."""
    if not pytestconfig.getoption("--no-namespace"):
        debug.enter_namespace()


@fixture
def test_ctfroute_conf() -> YamlConfig:
    """
    Ctfroute configuration used by "local" tests.

    I.e. the "unit" tests that typically also use enter_namespace.
    """
    return read_yaml_conf(LOCAL_CONF_PATH)


@fixture
def integration_ctfroute_conf(pytestconfig: Config) -> YamlConfig:
    """
    Ctfroute configuration used by the docker test setup.

    Primarily used by the integration tests.
    """
    conf_path = pytestconfig.getoption("ctfroute_config")
    return read_yaml_conf(conf_path or DOCKER_CONF_PATH)


@fixture
def integration_ctfroute_client(integration_ctfroute_conf) -> VulnboxesClient:
    """
    VulnboxesClient for the local docker setup.

    Primarily used by the integration tests.
    """
    return VulnboxesClient(integration_ctfroute_conf.initial_state)


@fixture
def k8s_ctfroute_client(pytestconfig) -> VulnboxesClient:
    """
    VulnboxesClient for the kubernetes setup.

    Primarily used by the integration tests.
    """
    conf_path = pytestconfig.getoption("ctfroute_config")
    conf = read_yaml_conf(conf_path or K8S_CONF_PATH)
    return VulnboxesClient(conf.initial_state)


@fixture
def k8s_namespace(pytestconfig) -> str:
    # Explicitly set?
    ns = pytestconfig.getoption("k8s_namespace")

    # Explicit ctfroute config passed?
    if ns is None and (conf_path := pytestconfig.getoption("ctfroute_config")):
        conf = read_yaml_conf(conf_path)
        for adapter in conf.adapters:
            if adapter.type == "kubernetes":
                assert isinstance(adapter, KubernetesAdapterConfig)
                ns = adapter.namespace

    ns = ns or "local-docker-test"
    return ns


@pytest.fixture(scope="session")
def nft(maybe_enter_namespace) -> Nftables:
    return Nftables()


@fixture(scope="package")
def gates_initial_state(configs_dir: Path) -> CtfRouteState:
    state = CtfRouteState.from_initial(
        read_yaml_conf(configs_dir / "gates-tests.yml").initial_state
    )
    return state


@fixture(scope="module")
def ready_gatekeeper(gates_initial_state, maybe_enter_namespace) -> GateKeeper:
    """Gatekeeper that was set up but isn't "running" yet."""
    gc = GateKeeper(
        initial_state=gates_initial_state, context=LocalContext(self_id="test")
    )
    gc._setup()
    return gc


@fixture(scope="session")
def api_client():
    """Return test client for FastAPI REST server."""
    return TestClient(rest_server)


@fixture(scope="session")
def max_vulnboxes(pytestconfig) -> int | None:
    return pytestconfig.getoption("max_vulnboxes")
