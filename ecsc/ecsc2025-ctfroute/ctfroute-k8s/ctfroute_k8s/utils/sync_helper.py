from datetime import datetime

from . import build_conn_gate, build_raw_gate


def add_raw_gate(
    *,
    namespace: str,
    name: str,
    conn_src: str,
    conn_dst: str,
    rule: str,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
):
    gate = build_raw_gate(
        namespace=namespace,
        name=name,
        conn_src=conn_src,
        conn_dst=conn_dst,
        rule=rule,
        from_time=from_time,
        to_time=to_time,
    )
    gate.create()


def add_connection_gate(
    *,
    namespace: str,
    name: str,
    conn_src: str,
    conn_dst: str,
    expression: str | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
):
    gate = build_conn_gate(
        namespace=namespace,
        name=name,
        conn_src=conn_src,
        conn_dst=conn_dst,
        expression=expression,
        from_time=from_time,
        to_time=to_time,
    )
    gate.create()
