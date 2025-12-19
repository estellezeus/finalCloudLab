import boto3
import requests
import json
import time

REGION = "us-east-1"
AMI_ID = "ami-0c398cb65a93047f2"
KEY_NAME = "finalLabKey"
SECURITY_GROUP_ID = "sg-07eb91b8897bb1816"
PROXY_PORT = 5000
GATEKEEPER_PORT = 4000

ec2 = boto3.resource("ec2", region_name=REGION)
ec2_client = boto3.client("ec2", region_name=REGION)

# -------------------------------
# USER DATA SCRIPTS
# -------------------------------

user_data_mysql = """#!/bin/bash
apt update -y
apt install -y mysql-server wget unzip
systemctl enable mysql
systemctl start mysql

until mysqladmin ping >/dev/null 2>&1; do
  sleep 2
done

cd /tmp
wget -q https://downloads.mysql.com/docs/sakila-db.zip
unzip -o sakila-db.zip

mysql < sakila-db/sakila-schema.sql
mysql < sakila-db/sakila-data.sql

mysql <<EOF
CREATE USER IF NOT EXISTS 'estelle'@'%' IDENTIFIED BY 'estelle';
GRANT ALL PRIVILEGES ON *.* TO 'estelle'@'%';
FLUSH PRIVILEGES;
EOF
"""

# -------------------------------
# CREATE MYSQL INSTANCES
# -------------------------------

mysql_instances = ec2.create_instances(
    ImageId=AMI_ID,
    InstanceType="t2.micro",
    MinCount=3,
    MaxCount=3,
    KeyName=KEY_NAME,
    SecurityGroupIds=[SECURITY_GROUP_ID],
    UserData=user_data_mysql
)

mysql_instances[0].create_tags(Tags=[
    {"Key": "Role", "Value": "manager"},
    {"Key": "Name", "Value": "mysql-manager"}
])

for i, inst in enumerate(mysql_instances[1:], start=1):
    inst.create_tags(Tags=[
        {"Key": "Role", "Value": "worker"},
        {"Key": "Name", "Value": f"mysql-worker-{i}"}
    ])

for inst in mysql_instances:
    inst.wait_until_running()
    inst.reload()

# -------------------------------
# WRITE INSTANCE IDS FILE
# -------------------------------

instance_ids = [i.id for i in mysql_instances]
with open("mysql_instance_ids.txt", "w") as f:
    for iid in instance_ids:
        f.write(iid + "\n")

# -------------------------------
# RESOLVE PRIVATE IPS
# -------------------------------

desc = ec2_client.describe_instances(InstanceIds=instance_ids)

id_to_ip = {}
for r in desc["Reservations"]:
    for i in r["Instances"]:
        id_to_ip[i["InstanceId"]] = i["PrivateIpAddress"]

db_hosts = {
    "master": id_to_ip[instance_ids[0]],
    "workers": [id_to_ip[i] for i in instance_ids[1:]]
}

print("DB HOSTS:", db_hosts)

# -------------------------------
# CREATE PROXY INSTANCE
# -------------------------------

proxy_user_data = f"""#!/bin/bash
apt update -y
apt install -y python3-pip
pip3 install flask pymysql requests

cat <<EOF > /home/ubuntu/db_hosts.json
{json.dumps(db_hosts, indent=2)}
EOF

curl -L -o /home/ubuntu/proxy.py https://raw.githubusercontent.com/estellezeus/finalCloudLab/main/proxy.py
sleep 30
python3 /home/ubuntu/proxy.py &
"""

proxy = ec2.create_instances(
    ImageId=AMI_ID,
    InstanceType="t2.large",
    MinCount=1,
    MaxCount=1,
    KeyName=KEY_NAME,
    SecurityGroupIds=[SECURITY_GROUP_ID],
    UserData=proxy_user_data,
    TagSpecifications=[{
        "ResourceType": "instance",
        "Tags": [
            {"Key": "Name", "Value": "mysql-proxy"},
            {"Key": "Role", "Value": "proxy"}
        ]
    }]
)[0]

proxy.wait_until_running()
proxy.reload()

# -------------------------------
# CREATE GATEKEEPER INSTANCE
# -------------------------------

gatekeeper_user_data = f"""#!/bin/bash
apt update -y
apt install -y python3-pip
pip3 install flask requests boto3

curl -L -o /home/ubuntu/gatekeeper.py https://raw.githubusercontent.com/estellezeus/finalCloudLab/main/gatekeeper.py

cat <<EOF >/home/ubuntu/gatekeeper.env
GATEKEEPER_TOKEN=changeme
PROXY_URL=http://{proxy.private_ip_address}:{PROXY_PORT}/query
AWS_REGION={REGION}
EOF

echo 'source /home/ubuntu/gatekeeper.env' >> /home/ubuntu/.bashrc
nohup env $(cat /home/ubuntu/gatekeeper.env | xargs) python3 /home/ubuntu/gatekeeper.py > /var/log/gatekeeper.log 2>&1 &
"""

gatekeeper = ec2.create_instances(
    ImageId=AMI_ID,
    InstanceType="t2.large",
    MinCount=1,
    MaxCount=1,
    KeyName=KEY_NAME,
    SecurityGroupIds=[SECURITY_GROUP_ID],
    UserData=gatekeeper_user_data,
    TagSpecifications=[{
        "ResourceType": "instance",
        "Tags": [
            {"Key": "Name", "Value": "mysql-gatekeeper"},
            {"Key": "Role", "Value": "gateway"}
        ]
    }]
)[0]

gatekeeper.wait_until_running()
gatekeeper.reload()

# -------------------------------
# OPEN PORT 5000
# -------------------------------

def get_my_public_ip():
    return requests.get("https://checkip.amazonaws.com").text.strip() + "/32"

sg = ec2_client.describe_security_groups(GroupIds=[SECURITY_GROUP_ID])["SecurityGroups"][0]
cidr = get_my_public_ip()

already = any(
    perm.get("FromPort") == PROXY_PORT and
    any(r["CidrIp"] == cidr for r in perm.get("IpRanges", []))
    for perm in sg["IpPermissions"]
)

if not already:
    ec2_client.authorize_security_group_ingress(
        GroupId=SECURITY_GROUP_ID,
        IpPermissions=[{
            "IpProtocol": "tcp",
            "FromPort": PROXY_PORT,
            "ToPort": PROXY_PORT,
            "IpRanges": [{"CidrIp": cidr}]
        }]
    )

print("Proxy public IP:", proxy.public_ip_address)
print("Proxy endpoint: http://{}:5000/query".format(proxy.public_ip_address))

# -------------------------------
# OPEN PORT 4000 FOR GATEKEEPER
# -------------------------------

sg = ec2_client.describe_security_groups(GroupIds=[SECURITY_GROUP_ID])["SecurityGroups"][0]
cidr = get_my_public_ip()

already = any(
    perm.get("FromPort") == GATEKEEPER_PORT and
    any(r["CidrIp"] == cidr for r in perm.get("IpRanges", []))
    for perm in sg["IpPermissions"]
)

if not already:
    ec2_client.authorize_security_group_ingress(
        GroupId=SECURITY_GROUP_ID,
        IpPermissions=[{
            "IpProtocol": "tcp",
            "FromPort": GATEKEEPER_PORT,
            "ToPort": GATEKEEPER_PORT,
            "IpRanges": [{"CidrIp": cidr}]
        }]
    )

print("Gatekeeper public IP:", gatekeeper.public_ip_address)
print("Gatekeeper endpoint: http://{}:{}/query".format(gatekeeper.public_ip_address, GATEKEEPER_PORT))
