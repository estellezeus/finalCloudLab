from flask import Flask, request, jsonify
import boto3
import pymysql
import random
import subprocess
import time

# =============================
# CONFIGURATION
# =============================
FORWARDING_STRATEGY = "custom"   # direct | random | custom
MYSQL_USER = "estelle"
MYSQL_PASSWORD = "estelle"
MYSQL_DB = "sakila"
AWS_REGION = "us-east-1"

# =============================
# AWS DISCOVERY
# =============================
ec2 = boto3.client("ec2", region_name=AWS_REGION)

def discover_mysql_instances():
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Role", "Values": ["master", "worker"]},
            {"Name": "instance-state-name", "Values": ["running"]}
        ]
    )

    master = None
    workers = []

    for r in response["Reservations"]:
        for i in r["Instances"]:
            role = next(t["Value"] for t in i["Tags"] if t["Key"] == "Role")
            ip = i["PrivateIpAddress"]

            if role == "master":
                master = ip
            elif role == "worker":
                workers.append(ip)

    if not master or not workers:
        raise RuntimeError("MySQL instances not discovered correctly")

    return master, workers

MASTER_IP, WORKER_IPS = discover_mysql_instances()

MASTER_DB = {
    "host": MASTER_IP,
    "user": MYSQL_USER,
    "password": MYSQL_PASSWORD,
    "db": MYSQL_DB
}

WORKERS = [
    {"host": ip, "user": MYSQL_USER, "password": MYSQL_PASSWORD, "db": MYSQL_DB}
    for ip in WORKER_IPS
]

# =============================
# APPLICATION
# =============================
app = Flask(__name__)

# =============================
# UTILS
# =============================
def get_query_type(query: str) -> str:
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
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
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
# LOAD BALANCING STRATEGIES
# =============================
def direct_strategy():
    return MASTER_DB


def random_strategy(query_type):
    if query_type == "WRITE":
        return MASTER_DB
    return random.choice(WORKERS)


def custom_strategy(query_type):
    if query_type == "WRITE":
        return MASTER_DB

    latencies = {w["host"]: ping(w["host"]) for w in WORKERS}
    best = min(latencies, key=latencies.get)

    for w in WORKERS:
        if w["host"] == best:
            return w


def choose_target(query):
    query_type = get_query_type(query)

    if FORWARDING_STRATEGY == "direct":
        return direct_strategy()

    if FORWARDING_STRATEGY == "random":
        return random_strategy(query_type)

    if FORWARDING_STRATEGY == "custom":
        return custom_strategy(query_type)

    return MASTER_DB

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
# API
# =============================
@app.route("/query", methods=["POST"])
def handle_query():
    data = request.json
    query = data.get("query")

    if not query:
        return jsonify({"error": "No SQL query provided"}), 400

    target = choose_target(query)
    start = time.time()
    result = execute_query(target, query)
    duration = round((time.time() - start) * 1000, 2)

    return jsonify({
        "strategy": FORWARDING_STRATEGY,
        "query_type": get_query_type(query),
        "target_host": target["host"],
        "duration_ms": duration,
        "result": result
    })

# =============================
# MAIN
# =============================
if __name__ == "__main__":
    print("Master:", MASTER_IP)
    print("Workers:", WORKER_IPS)
    app.run(host="0.0.0.0", port=5000)
