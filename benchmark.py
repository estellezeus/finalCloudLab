import requests
import time
import json
import boto3

AWS_REGION = "us-east-1"

READ_REQUESTS = 1000
WRITE_REQUESTS = 1000

READ_QUERY = "SELECT 1"
WRITE_QUERY = "INSERT INTO actor (first_name, last_name) VALUES ('Bench', 'Mark')"

# =============================
# DISCOVER PROXY IP
# =============================
ec2 = boto3.client("ec2", region_name=AWS_REGION)

def discover_proxy_ip():
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Role", "Values": ["proxy"]},
            {"Name": "instance-state-name", "Values": ["running"]}
        ]
    )

    for r in response["Reservations"]:
        for i in r["Instances"]:
            return i["PublicIpAddress"]

    raise RuntimeError("Proxy instance not found")

proxy_ip = discover_proxy_ip()
BASE_URL = f"http://{proxy_ip}:5000"

print("Proxy discovered at:", BASE_URL)

# =============================
# HTTP HELPERS
# =============================
def post_query(query):
    return requests.post(
        f"{BASE_URL}/query",
        json={"query": query},
        timeout=5
    )

def get_stats():
    return requests.get(
        f"{BASE_URL}/stats",
        timeout=5
    ).json()

# =============================
# BENCHMARK
# =============================
def run_benchmark(strategy_name):
    print(f"\n=== Running benchmark for strategy: {strategy_name} ===")

    errors = 0
    start = time.time()

    # READ
    for i in range(READ_REQUESTS):
        r = post_query(READ_QUERY)
        print(f"read {i}")
        if r.status_code != 200:
            errors += 1

    # WRITE
    for j in range(WRITE_REQUESTS):
        r = post_query(WRITE_QUERY)
        print(f"write {j}")
        if r.status_code != 200:
            errors += 1

    duration = round(time.time() - start, 2)

    stats = get_stats()

    result = {
        "strategy": strategy_name,
        "read_requests": READ_REQUESTS,
        "write_requests": WRITE_REQUESTS,
        "total_requests": READ_REQUESTS + WRITE_REQUESTS,
        "errors": errors,
        "total_time_sec": duration,
        "avg_latency_ms": round(duration * 1000 / (READ_REQUESTS + WRITE_REQUESTS), 2),
        "stats": stats
    }

    filename = f"results_{strategy_name}.json"
    with open(filename, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Results written to {filename}")

# =============================
# MAIN
# =============================
if __name__ == "__main__":
    run_benchmark("direct")
    run_benchmark("random")
    run_benchmark("custom")
