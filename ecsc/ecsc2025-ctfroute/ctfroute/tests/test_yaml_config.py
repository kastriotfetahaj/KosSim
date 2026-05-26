from pathlib import Path

from pytest import fixture, raises
from yaml import safe_dump, safe_load

from ctfroute.adapters.yaml_conf import read_yaml_conf
from ctfroute.exceptions import BadConfiguration


@fixture
def default_drivers_config(configs_dir: Path) -> Path:
    return configs_dir / "default-drivers.yml"


@fixture
def all_known_configs(configs_dir: Path) -> list[Path]:
    all_configs = list(configs_dir.glob("**/*.yml"))
    all_configs += list((configs_dir / "../../../docker").glob("*ctfroute.yml"))
    return all_configs


def test_known_configs_load(all_known_configs, subtests):
    for config in all_known_configs:
        with subtests.test(msg=str(config)):
            read_yaml_conf(config)


def test_default_drivers_config(default_drivers_config: Path) -> None:
    """Check that the read_yaml_conf method populates drivers with defaults."""
    config = read_yaml_conf(default_drivers_config)

    for router in config.initial_state.routers:
        assert router.connectivity is not None

    for team in config.initial_state.teams:
        assert team.anonymization is not None


def test_missing_drivers_raises(tmp_path, default_drivers_config) -> None:
    """
    Raise if drivers are missing.

    read_yaml_conf() should raise BadConfiguration if there are no connectivity /
    anonymization drivers configured for a router / team.
    """
    config_file = tmp_path / "missing-drivers.yaml"

    config = safe_load(default_drivers_config.read_text())
    del config["defaults"]["teams"]["anonymization"]
    with open(config_file, "w") as f:
        safe_dump(config, f)

    with raises(BadConfiguration):
        read_yaml_conf(config_file)

    config = safe_load(default_drivers_config.read_text())
    del config["defaults"]["routers"]["connectivity"]
    with open(config_file, "w") as f:
        safe_dump(config, f)

    with raises(BadConfiguration):
        read_yaml_conf(config_file)
