from __future__ import annotations

import os
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request


app = Flask(__name__)

NAT_TEAM = os.getenv("NAT_TEAM", "team")
HTTP_TIMEOUT = float(os.getenv("NAT_HTTP_TIMEOUT", "4"))
ALLOWED_SCHEMES = {"http", "https"}


def _validate_target(url: str) -> tuple[bool, str]:
    if not url:
        return False, "missing url"
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, "only http/https are allowed"
    if not parsed.netloc:
        return False, "invalid netloc"
    return True, ""


@app.get("/")
def root():
    return jsonify({"service": "nat-gateway", "nat_team": NAT_TEAM})


@app.get("/health")
def health():
    return jsonify({"status": "up", "nat_team": NAT_TEAM})


@app.get("/fetch")
def fetch():
    target_url = request.args.get("url", "").strip()
    valid, reason = _validate_target(target_url)
    if not valid:
        return jsonify({"error": reason}), 400

    try:
        upstream = requests.get(
            target_url,
            timeout=HTTP_TIMEOUT,
            headers={"X-Nat-Team": NAT_TEAM},
        )
    except requests.RequestException as exc:
        return jsonify({"error": str(exc), "nat_team": NAT_TEAM}), 502

    return jsonify(
        {
            "nat_team": NAT_TEAM,
            "target_url": target_url,
            "status_code": upstream.status_code,
            "target_response_body": upstream.text,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
