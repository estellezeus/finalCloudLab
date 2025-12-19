from flask import Flask, request, jsonify
import boto3
import pymysql
import random
import subprocess
import time
import json
from datetime import datetime

# =============================
# CONFIGURATION
# =============================
AWS_REGION = "us-east-1"
FORWARDING_STRATEGY = "custom"  # direct | random | custom

MYSQL_USER = "estelle"
MYSQL_PASSWORD = "estelle"
MYSQL_DB = "sakila"

STATS_FILE = "/home/ubuntu/proxy_stats.json"

# =============================
# AWS DISCOVERY
# =============================
ec2 = boto3.client("ec2", region_name=AWS_REGION)

def discover_mysql_instances():
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Role", "Values": ["manager", "worker"]},
            {"Name": "instance-state-name", "Values": ["running"]}
        ]
    )

    manager = None
    workers = []

    for r in response["Reservations"]:
        for i in r["Instances"]:
            role = next(t["Value"] for t in i["Tags"] if t["Key"] == "Role")
            ip = i["PrivateIpAddress"]

            if role == "manager":
                manager = ip
            elif role == "worker":
                workers.append(ip)

    if not manager or len(workers) != 2:
        raise RuntimeError("MySQL cluster not discovered correctly")

    return manager, workers

MANAGER_IP, WORKER_IPS = discover_mysql_instances()

# =============================
# DATABASE CONFIG
# =============================
MANAGER_DB = {
    "host": MANAGER_IP,
    "user": MYSQL_USER,
    "password": MYSQL_PASSWORD,
    "db": MYSQL_DB
}

WORKERS = [
    {"host": WORKER_IPS[0], "user": MYSQL_USER, "password": MYSQL_PASSWORD, "db": MYSQL_DB},
    {"host": WORKER_IPS[1], "user": MYSQL_USER, "password": MYSQL_PASSWORD, "db": MYSQL_DB}
]

# =============================
# STATS
# =============================
STATS = {
    "strategy": FORWARDING_STRATEGY,
    "proxy": {"READ": 0, "WRITE": 0},
    "manager": {
        "host": MANAGER_IP,
        "READ": 0,
        "WRITE": 0
    },
    "workers": {
        "worker1": {
            "host": WORKERS[0]["host"],
            "READ": 0,
            "WRITE": 0
        },
        "worker2": {
            "host": WORKERS[1]["host"],
            "READ": 0,
            "WRITE": 0
        }
    },
    "last_updated": None
}

def save_stats():
    STATS["last_updated"] = datetime.utcnow().isoformat()
    with open(STATS_FILE, "w") as f:
        json.dump(STATS, f, indent=2)

# =============================
# APP
# =============================
app = Flask(__name__)

# =============================
# UTILS
# =============================
def get_query_type(query):
    query = query.strip().lower()
    if query.startswith("select"):
        return "READ"
    return "WRITE"

def connect(db):
    return pymysql.connect(
        host=db["host"],
        user=db["user"],
        password=db["password"],
        database=db["db"],
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=3
    )

def ping(host):
    try:
        result = subprocess.run(
            ["ping", "-c", "1", host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2
        )
        for line in result.stdout.splitlines():
            if "time=" in line:
                return float(line.split("time=")[1].split()[0])
    except Exception:
        pass
    return float("inf")

# =============================
# STRATEGIES
# =============================
def direct_strategy():
    return MANAGER_DB

def random_strategy(query_type):
    if query_type == "WRITE":
        return MANAGER_DB
    return random.choice(WORKERS)

def custom_strategy(query_type):
    if query_type == "WRITE":
        return MANAGER_DB

    latencies = {w["host"]: ping(w["host"]) for w in WORKERS}
    best_host = min(latencies, key=latencies.get)

    for w in WORKERS:
        if w["host"] == best_host:
            return w

def choose_target(query):
    query_type = get_query_type(query)

    if FORWARDING_STRATEGY == "direct":
        return direct_strategy()

    if FORWARDING_STRATEGY == "random":
        return random_strategy(query_type)

    return custom_strategy(query_type)

# =============================
# QUERY EXECUTION
# =============================
def execute_query(db, query):
    conn = connect(db)
    try:
        with conn.cursor() as cursor:
            cursor.execute(query)
            if query.strip().lower().startswith("select"):
                return cursor.fetchall()
            return {"status": "OK"}
    finally:
        conn.close()

# =============================
# ROUTES
# =============================
@app.route("/query", methods=["POST"])
def handle_query():
    data = request.json
    query = data.get("query")

    if not query:
        return jsonify({"error": "No SQL query provided"}), 400

    query_type = get_query_type(query)
    STATS["proxy"][query_type] += 1

    target = choose_target(query)

    # Update routing stats
    if target["host"] == MANAGER_DB["host"]:
        STATS["manager"][query_type] += 1
    elif target["host"] == STATS["workers"]["worker1"]["host"]:
        STATS["workers"]["worker1"][query_type] += 1
    elif target["host"] == STATS["workers"]["worker2"]["host"]:
        STATS["workers"]["worker2"][query_type] += 1

    start = time.time()
    result = execute_query(target, query)
    duration = round((time.time() - start) * 1000, 2)

    save_stats()

    return jsonify({
        "strategy": FORWARDING_STRATEGY,
        "query_type": query_type,
        "target": target["host"],
        "duration_ms": duration,
        "result": result
    })

@app.route("/stats", methods=["GET"])
def stats():
    return jsonify(STATS)

# =============================
# MAIN
# =============================
if __name__ == "__main__":
    print("Proxy running")
    print("Manager:", MANAGER_IP)
    print("Workers:", WORKER_IPS)
    app.run(host="0.0.0.0", port=5000)
