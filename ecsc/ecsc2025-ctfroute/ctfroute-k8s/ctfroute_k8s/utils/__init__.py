from datetime import datetime

from cloudcoil.apimachinery import ObjectMeta

# cloudcoil generated models from crds.yaml
from ctfroute_k8s.models.v1 import Gate, Period
from ctfroute_k8s.models.v1 import GateSpec as RawGateSpec  # Spec for raw gates
from ctfroute_k8s.models.v1 import GateSpecModel as ConnGateSpec  # Spec for conn gates
from ctfroute_k8s.models.v1 import GateSpecModel1 as GateSpec  # Actual gate spec


def build_raw_gate(
    *,
    namespace: str,
    name: str,
    conn_src: str,
    conn_dst: str,
    rule: str,
    from_time: datetime | None,
    to_time: datetime | None,
) -> Gate:
    if from_time and from_time.tzinfo is None:
        raise ValueError("from_time must be timezone-aware")
    if to_time and to_time.tzinfo is None:
        raise ValueError("to_time must be timezone-aware")
    spec = RawGateSpec(
        type="raw",
        conn_src=conn_src,
        conn_dst=conn_dst,
        rule=rule,
        period=Period(
            from_time=str(from_time) if from_time else None,
            to_time=str(to_time) if to_time else None,
        ),
    )
    return Gate(
        metadata=ObjectMeta(
            name=name,
            namespace=namespace,
        ),
        spec=GateSpec(spec),
    )


def build_conn_gate(
    *,
    name: str,
    conn_src: str,
    conn_dst: str,
    namespace: str | None,
    expression: str | None,
    from_time: datetime | None,
    to_time: datetime | None,
) -> Gate:
    if from_time and from_time.tzinfo is None:
        raise ValueError("from_time must be timezone-aware")
    if to_time and to_time.tzinfo is None:
        raise ValueError("to_time must be timezone-aware")

    spec = ConnGateSpec(
        type="connection",
        conn_src=conn_src,
        conn_dst=conn_dst,
        expression=expression,
        period=Period(
            from_time=str(from_time) if from_time else None,
            to_time=str(to_time) if to_time else None,
        ),
    )
    return Gate(
        metadata=ObjectMeta(
            name=name,
            namespace=namespace,
        ),
        spec=GateSpec(spec),
    )
