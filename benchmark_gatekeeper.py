import os
import time
import json
import requests
import boto3

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
GATEKEEPER_PORT = int(os.getenv("GATEKEEPER_PORT", "4000"))
GATEKEEPER_ROLE = os.getenv("GATEKEEPER_ROLE", "gateway")
GATEKEEPER_TOKEN = os.getenv("GATEKEEPER_TOKEN", "changeme")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "5"))

PROXY_PORT = int(os.getenv("PROXY_PORT", "5000"))
PROXY_ROLE = os.getenv("PROXY_ROLE", "proxy")
PROXY_STATS_URL = os.getenv("PROXY_STATS_URL", "")
RESET_PROXY_STATS = os.getenv("RESET_PROXY_STATS", "true").lower() == "true"

READ_REQUESTS = int(os.getenv("READ_REQUESTS", "10"))
WRITE_REQUESTS = int(os.getenv("WRITE_REQUESTS", "10"))
BLOCKED_REQUESTS = int(os.getenv("BLOCKED_REQUESTS", "3"))

READ_QUERY = os.getenv("READ_QUERY", "SELECT 1")
WRITE_QUERY = os.getenv(
    "WRITE_QUERY",
    "INSERT INTO actor (first_name, last_name) VALUES ('Gate', 'Keeper')",
)
BLOCKED_QUERY = os.getenv("BLOCKED_QUERY", "DROP TABLE actor")

RESULTS_FILE = os.getenv("RESULTS_FILE", "results_gatekeeper.json")


ec2 = boto3.client("ec2", region_name=AWS_REGION)


def discover_gatekeeper_ip():
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Role", "Values": [GATEKEEPER_ROLE]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )

    for reservation in response.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            ip = instance.get("PublicIpAddress") or instance.get("PrivateIpAddress")
            if ip:
                return ip

    raise RuntimeError("Gatekeeper instance not found")


def discover_proxy_ip():
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Role", "Values": [PROXY_ROLE]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )

    for reservation in response.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            ip = instance.get("PublicIpAddress") or instance.get("PrivateIpAddress")
            if ip:
                return ip

    raise RuntimeError("Proxy instance not found")


GATEKEEPER_IP = discover_gatekeeper_ip()
BASE_URL = f"http://{GATEKEEPER_IP}:{GATEKEEPER_PORT}"

print("Gatekeeper discovered at:", BASE_URL)


# =============================
# HTTP HELPERS
# =============================

def post_query(query, token):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return requests.post(
        f"{BASE_URL}/query",
        json={"query": query},
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )


def get_proxy_stats_url():
    if PROXY_STATS_URL:
        return PROXY_STATS_URL
    proxy_ip = discover_proxy_ip()
    return f"http://{proxy_ip}:{PROXY_PORT}/stats"


def fetch_proxy_stats():
    try:
        stats_url = get_proxy_stats_url()
    except Exception as exc:
        return None, None, f"proxy discovery failed: {exc}"

    try:
        resp = requests.get(stats_url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return stats_url, None, f"proxy stats status {resp.status_code}"
        return stats_url, resp.json(), None
    except Exception as exc:
        return stats_url, None, f"proxy stats request failed: {exc}"


def reset_proxy_stats():
    try:
        stats_url = get_proxy_stats_url()
    except Exception as exc:
        return None, f"proxy discovery failed: {exc}"

    reset_url = stats_url.replace("/stats", "/stats/reset")
    try:
        resp = requests.post(reset_url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return reset_url, f"proxy reset status {resp.status_code}"
        return reset_url, None
    except Exception as exc:
        return reset_url, f"proxy reset failed: {exc}"


# =============================
# BENCHMARK
# =============================

def run_benchmark():
    if not GATEKEEPER_TOKEN:
        raise RuntimeError("GATEKEEPER_TOKEN is required to run the benchmark")

    errors = 0
    latencies_ms = []
    reset_url = None
    reset_error = None

    print("\n=== Gatekeeper benchmark ===")

    if RESET_PROXY_STATS:
        reset_url, reset_error = reset_proxy_stats()

    # Unauthorized check
    unauth = post_query(READ_QUERY, token="")
    unauth_status = unauth.status_code

    start = time.time()

    # READ
    for i in range(READ_REQUESTS):
        req_start = time.time()
        r = post_query(READ_QUERY, GATEKEEPER_TOKEN)
        latencies_ms.append(round((time.time() - req_start) * 1000, 2))
        print(f"read {i}")
        if r.status_code != 200:
            errors += 1

    # WRITE
    for j in range(WRITE_REQUESTS):
        req_start = time.time()
        r = post_query(WRITE_QUERY, GATEKEEPER_TOKEN)
        latencies_ms.append(round((time.time() - req_start) * 1000, 2))
        print(f"write {j}")
        if r.status_code != 200:
            errors += 1

    # BLOCKED
    for k in range(BLOCKED_REQUESTS):
        req_start = time.time()
        r = post_query(BLOCKED_QUERY, GATEKEEPER_TOKEN)
        latencies_ms.append(round((time.time() - req_start) * 1000, 2))
        print(f"blocked {k}")
        if r.status_code != 400:
            errors += 1

    duration = round(time.time() - start, 2)

    proxy_stats_url, proxy_stats, proxy_stats_error = fetch_proxy_stats()

    result = {
        "gatekeeper_url": BASE_URL,
        "proxy_reset_url": reset_url,
        "proxy_reset_error": reset_error,
        "unauthorized_status": unauth_status,
        "read_requests": READ_REQUESTS,
        "write_requests": WRITE_REQUESTS,
        "blocked_requests": BLOCKED_REQUESTS,
        "total_requests": READ_REQUESTS + WRITE_REQUESTS + BLOCKED_REQUESTS + 1,
        "errors": errors,
        "total_time_sec": duration,
        "avg_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 2) if latencies_ms else 0,
        "latency_samples_ms": latencies_ms[:10],
        "proxy_stats_url": proxy_stats_url,
        "proxy_stats": proxy_stats,
        "proxy_stats_error": proxy_stats_error,
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Results written to {RESULTS_FILE}")


# =============================
# MAIN
# =============================
if __name__ == "__main__":
    run_benchmark()
