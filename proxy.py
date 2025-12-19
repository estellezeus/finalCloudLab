from flask import Flask, request, jsonify
import pymysql
import random
import subprocess
import time
import json

FORWARDING_STRATEGY = "custom"
MYSQL_USER = "estelle"
MYSQL_PASSWORD = "estelle"
MYSQL_DB = "sakila"

with open("/home/ubuntu/db_hosts.json") as f:
    hosts = json.load(f)

MASTER_DB = {
    "host": hosts["master"],
    "user": MYSQL_USER,
    "password": MYSQL_PASSWORD,
    "db": MYSQL_DB
}

WORKERS = [
    {
        "host": ip,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
        "db": MYSQL_DB
    }
    for ip in hosts["workers"]
]

app = Flask(__name__)

def get_query_type(query):
    return "READ" if query.strip().lower().startswith("select") else "WRITE"

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
        out = subprocess.check_output(["ping", "-c", "1", host], timeout=2).decode()
        return float(out.split("time=")[1].split()[0])
    except:
        return float("inf")

def choose_target(query):
    qt = get_query_type(query)

    if FORWARDING_STRATEGY == "direct" or qt == "WRITE":
        return MASTER_DB

    if FORWARDING_STRATEGY == "random":
        return random.choice(WORKERS)

    lat = {w["host"]: ping(w["host"]) for w in WORKERS}
    best = min(lat, key=lat.get)

    return next(w for w in WORKERS if w["host"] == best)

@app.route("/query", methods=["POST"])
def handle():
    query = request.json.get("query")
    db = choose_target(query)

    start = time.time()
    conn = connect(db)
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            res = cur.fetchall() if query.lower().startswith("select") else {"status": "OK"}
    finally:
        conn.close()

    return jsonify({
        "target": db["host"],
        "strategy": FORWARDING_STRATEGY,
        "duration_ms": round((time.time() - start) * 1000, 2),
        "result": res
    })

if __name__ == "__main__":
    print("Master:", MASTER_DB["host"])
    print("Workers:", [w["host"] for w in WORKERS])
    app.run(host="0.0.0.0", port=5000)
