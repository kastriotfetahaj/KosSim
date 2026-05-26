from ctfroute.state import internal
from ctfroute.state.internal import to_external


def test_convert_to_internal(integration_ctfroute_conf):
    state = internal.CtfRouteState.from_initial(integration_ctfroute_conf.initial_state)

    assert isinstance(state.teams[0], internal.Team)
    assert isinstance(state.routers[0], internal.Router)

    assert isinstance(state.teams[0].internal_state, dict)
    assert isinstance(state.routers[0].internal_state, dict)


def test_convert_to_external_team(integration_ctfroute_conf):
    state = internal.CtfRouteState.from_initial(integration_ctfroute_conf.initial_state)
    for idx, team in enumerate(state.teams):
        team.internal_state["TEST_ATTRIBUTE"] = "FOOBAR"
        assert integration_ctfroute_conf.initial_state.teams[idx] == to_external(team)


def test_convert_to_external_router(integration_ctfroute_conf):
    state = internal.CtfRouteState.from_initial(integration_ctfroute_conf.initial_state)
    for idx, router in enumerate(state.routers):
        router.internal_state["TEST_ATTRIBUTE"] = "FOOBAR"
        assert integration_ctfroute_conf.initial_state.routers[idx] == to_external(
            router
        )


def test_convert_to_external_gate(integration_ctfroute_conf):
    state = internal.CtfRouteState.from_initial(integration_ctfroute_conf.initial_state)
    for idx, gate in enumerate(state.gates):
        gate.internal_state["TEST_ATTRIBUTE"] = "FOOBAR"
        assert integration_ctfroute_conf.initial_state.gates[idx] == to_external(gate)
