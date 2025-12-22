from flask import Flask, request, jsonify
import pymysql
import time
import threading

# =========================
# CONFIG
# =========================
MYSQL_USER = "estelle"
MYSQL_PASSWORD = "estelle"
MYSQL_DB = "sakila"
MYSQL_PORT = 3306

INSTANCES_FILE = "/home/ubuntu/mysql_instance_ids.txt"

app = Flask(__name__)

# =========================
# LOAD INSTANCES
# =========================
with open(INSTANCES_FILE) as f:
    ips = [line.strip() for line in f if line.strip()]

MANAGER_IP = ips[0]
WORKER_IPS = ips[1:]

print("Manager:", MANAGER_IP)
print("Workers:", WORKER_IPS)

worker_index = 0
worker_lock = threading.Lock()

# =========================
# STATS (proxy only)
# =========================
STATS = {
    "proxy": {
        "READ": 0,
        "WRITE": 0
    },
    "manager": {
        "READ": 0,
        "WRITE": 0
    },
    "workers": {
        ip: {"READ": 0, "WRITE": 0} for ip in WORKER_IPS
    }
}

# =========================
# HELPERS
# =========================
def is_read_query(query: str) -> bool:
    return query.strip().lower().startswith("select")

def get_next_worker():
    global worker_index
    with worker_lock:
        ip = WORKER_IPS[worker_index]
        worker_index = (worker_index + 1) % len(WORKER_IPS)
    return ip

def connect(ip):
    return pymysql.connect(
        host=ip,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        port=MYSQL_PORT,
        connect_timeout=3,
        cursorclass=pymysql.cursors.DictCursor
    )

# =========================
# ROUTES
# =========================
@app.route("/query", methods=["POST"])
def query():
    data = request.get_json()
    sql = data.get("query")

    if not sql:
        return jsonify({"error": "Missing query"}), 400

    read = is_read_query(sql)
    qtype = "READ" if read else "WRITE"

    STATS["proxy"][qtype] += 1

    target_ip = None

    if read:
        target_ip = get_next_worker()
        STATS["workers"][target_ip]["READ"] += 1
    else:
        target_ip = MANAGER_IP
        STATS["manager"]["WRITE"] += 1

    start = time.time()

    try:
        conn = connect(target_ip)
        with conn.cursor() as cursor:
            cursor.execute(sql)
            if read:
                result = cursor.fetchall()
            else:
                conn.commit()
                result = {"rows_affected": cursor.rowcount}
        conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    duration = round((time.time() - start) * 1000, 2)

    return jsonify({
        "strategy": "proxy-no-boto3",
        "target": target_ip,
        "type": qtype,
        "duration_ms": duration,
        "result": result
    })

@app.route("/stats", methods=["GET"])
def stats():
    return jsonify(STATS)

@app.route("/stats/reset", methods=["POST"])
def reset_stats():
    STATS["proxy"]["READ"] = 0
    STATS["proxy"]["WRITE"] = 0
    STATS["manager"]["READ"] = 0
    STATS["manager"]["WRITE"] = 0
    for ip in STATS["workers"]:
        STATS["workers"][ip]["READ"] = 0
        STATS["workers"][ip]["WRITE"] = 0
    return jsonify({"status": "ok"})

# =========================
# START
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
