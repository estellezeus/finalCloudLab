import os
import re
import time
import boto3
import requests
from flask import Flask, request, jsonify

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
PROXY_URL = os.getenv("PROXY_URL")  # Optional override, e.g. http://<proxy-ip>:5000/query
GATEKEEPER_TOKEN = os.getenv("GATEKEEPER_TOKEN", "")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "5"))

ec2 = boto3.client("ec2", region_name=AWS_REGION)
app = Flask(__name__)


def discover_proxy_url():
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Role", "Values": ["proxy"]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )

    for reservation in response.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            ip = instance.get("PrivateIpAddress") or instance.get("PublicIpAddress")
            if ip:
                return f"http://{ip}:5000/query"

    raise RuntimeError("Proxy instance not found")


def authorized(req):
    token = req.headers.get("Authorization", "")
    if token.startswith("Bearer "):
        token = token.split(" ", 1)[1]
    return GATEKEEPER_TOKEN and token == GATEKEEPER_TOKEN


DENY_PATTERNS = [
    r"\bdrop\b",
    r"\btruncate\b",
    r"delete\s+from",
    r"\bshutdown\b",
    r"\bkill\b",
    r"\balter\b",
]


def is_safe_query(query: str) -> bool:
    lowered = query.strip().lower()
    return not any(re.search(pat, lowered) for pat in DENY_PATTERNS)


@app.route("/query", methods=["POST"])
def handle_query():
    if not authorized(request):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    query = data.get("query", "")

    if not query:
        return jsonify({"error": "No SQL query provided"}), 400

    if not is_safe_query(query):
        return jsonify({"error": "Query rejected by gatekeeper"}), 400

    target_url = PROXY_URL or discover_proxy_url()

    try:
        start = time.time()
        resp = requests.post(target_url, json={"query": query}, timeout=REQUEST_TIMEOUT)
        duration = round((time.time() - start) * 1000, 2)
    except Exception as exc:
        return jsonify({"error": f"Failed to reach proxy: {exc}"}), 502

    return jsonify(
        {
            "duration_ms": duration,
            "proxy_status": resp.status_code,
            "proxy_response": resp.json() if resp.headers.get("Content-Type", "").startswith("application/json") else resp.text,
        }
    ), resp.status_code


if __name__ == "__main__":
    print("Starting gatekeeper...")
    app.run(host="0.0.0.0", port=4000)
