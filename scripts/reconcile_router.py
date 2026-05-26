#!/usr/bin/env python3
"""Fetch the KosSim router bundle and apply it on a remote Linux router."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def download_bundle(control_url: str, token: str, out: Path) -> None:
    url = control_url.rstrip("/") + "/api/v1/network/router-bundle"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        out.write_bytes(resp.read())


def reconcile(control_url: str, token: str, host: str, remote_dir: str) -> None:
    with tempfile.TemporaryDirectory(prefix="kossim-router-") as tmp_raw:
        tmp = Path(tmp_raw)
        archive = tmp / "bundle.zip"
        bundle_dir = tmp / "bundle"
        download_bundle(control_url, token, archive)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(bundle_dir)
        apply_script = bundle_dir / "apply.sh"
        apply_script.chmod(0o755)

        _run(["ssh", host, "mkdir", "-p", remote_dir])
        _run(["scp", "-r", str(bundle_dir) + "/.", f"{host}:{remote_dir}/"])
        _run(["ssh", host, f"cd {remote_dir} && sudo sh apply.sh"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile generated KosSim WireGuard/nftables artifacts on a router.")
    parser.add_argument("--control-url", required=True, help="Control plane base URL, e.g. http://127.0.0.1:8088")
    parser.add_argument("--token", required=True, help="GAME_ADMIN_TOKEN value for bearer auth")
    parser.add_argument("--host", required=True, help="SSH target, e.g. root@router.example")
    parser.add_argument("--remote-dir", default="/opt/kossim-router", help="Remote staging directory")
    args = parser.parse_args()
    if not shutil.which("ssh") or not shutil.which("scp"):
        raise SystemExit("ssh and scp are required")
    reconcile(args.control_url, args.token, args.host, args.remote_dir)
    print(f"reconciled {args.host}:{args.remote_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
