import requests
import time
import boto3

AWS_REGION = "us-east-1"
REQUESTS_COUNT = 1000


ec2 = boto3.client("ec2", region_name=AWS_REGION)

def get_proxy_ip():
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

proxy_ip = get_proxy_ip()
url = f"http://{proxy_ip}:5000/query"

print("Proxy discovered at:", url)


payload = {
    "query": "SELECT COUNT(*) FROM actor;"
}

start = time.time()
errors = 0

for i in range(REQUESTS_COUNT):
    r = requests.post(url, json=payload)
    if r.status_code != 200:
        errors += 1

end = time.time()

print("Requests sent:", REQUESTS_COUNT)
print("Errors:", errors)
print("Total time (s):", round(end - start, 2))
print("Avg latency (ms):", round((end - start) * 1000 / REQUESTS_COUNT, 2))
