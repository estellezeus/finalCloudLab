import boto3
import requests


ec2 = boto3.resource("ec2", region_name="us-east-1")
ec2_client = boto3.client("ec2", region_name="us-east-1")
SECURITY_GROUP_ID = "sg-07eb91b8897bb1816"
PORT = 5000

# User data script to install MySQL on Ubuntu
user_data_mysql = """#!/bin/bash
apt update -y
apt install -y mysql-server wget unzip
systemctl enable mysql
systemctl start mysql

# Download Sakila
until mysqladmin ping >/dev/null 2>&1; do
  sleep 2
done

cd /tmp

if [ ! -f sakila-db.zip ]; then
  wget https://downloads.mysql.com/docs/sakila-db.zip
fi

unzip -o sakila-db.zip

# Install Sakila database
sudo mysql < sakila-db/sakila-schema.sql
sudo mysql < sakila-db/sakila-data.sql
"""

large_instance_user_data = """#!/bin/bash
apt update -y
apt install -y python3-pip
pip3 install flask pymysql boto3
"""

proxy_user_data = """#!/bin/bash
apt update -y
apt install -y python3-pip
pip3 install flask pymysql boto3 requests

curl -o /home/ubuntu/proxy.py https://github.com/estellezeus/finalCloudLab/blob/main/proxy.py
python3 /home/ubuntu/proxy.py &

"""



# Create 3 EC2 instances
mysql_db_intances = ec2.create_instances(
    ImageId="ami-0c398cb65a93047f2",  # Ubuntu 22.04 LTS
    InstanceType="t2.micro",
    MinCount=3,
    MaxCount=3,
    KeyName="finalLabKey",
    SecurityGroupIds=[SECURITY_GROUP_ID], # this sg opens the port 22 for ssh connexions
    UserData=user_data_mysql
)

# Tag first instance as manager
mysql_db_intances[0].create_tags(
    Tags=[
        {"Key": "Role", "Value": "manager"},
        {"Key": "Name", "Value": "mysql-manager"}
    ]
)

# Tag the other two as workers
for i, instance in enumerate(mysql_db_intances[1:], start=1):
    instance.create_tags(
        Tags=[
            {"Key": "Role", "Value": "worker"},
            {"Key": "Name", "Value": f"mysql-worker-{i}"}
        ]
)

print("3 t2.micro instances created with MySQL installed")

# The instances ids in a file
instance_ids = [j.id for j in mysql_db_intances]
with open("mysql_instance_ids.txt", "w") as f:
    for k in instance_ids:
        f.write(k + "\n")


# Create the proxy instance
proxy_instance = ec2.create_instances(
    ImageId="ami-0c398cb65a93047f2",
    InstanceType="t2.large",
    MinCount=1,
    MaxCount=1,
    KeyName="finalLabKey",
    SecurityGroupIds=[SECURITY_GROUP_ID],
    UserData=proxy_user_data,
    TagSpecifications=[
        {
            "ResourceType": "instance",
            "Tags": [
                {"Key": "Name", "Value": "mysql-proxy"},
                {"Key": "Role", "Value": "proxy"}
            ]
        }
    ]
)
print("Proxy created:", proxy_instance[0].id)


# Create the gateway instance

gateway_instances = ec2.create_instances(
    ImageId="ami-0c398cb65a93047f2",   # Ubuntu 22.04 LTS
    InstanceType="t2.large",
    MinCount=1,
    MaxCount=1,
    KeyName="finalLabKey",
    SecurityGroupIds=[SECURITY_GROUP_ID],
    UserData=large_instance_user_data,
    TagSpecifications=[
        {
            "ResourceType": "instance",
            "Tags": [
                {"Key": "Name", "Value": "mysql-gateway"},
                {"Key": "Role", "Value": "gateway"}
            ]
        }
    ]
)

gateway_instance = gateway_instances[0]
print("Gateway created:", gateway_instance.id)

def get_my_public_ip():
    return requests.get("https://checkip.amazonaws.com").text.strip()

def is_rule_present(sg, port, cidr):
    for perm in sg.get("IpPermissions", []):
        if perm.get("FromPort") == port and perm.get("ToPort") == port:
            for r in perm.get("IpRanges", []):
                if r.get("CidrIp") == cidr:
                    return True
    return False

def open_port_if_needed():
    my_ip = get_my_public_ip() + "/32"

    sg = ec2_client.describe_security_groups(
        GroupIds=[SECURITY_GROUP_ID]
    )["SecurityGroups"][0]

    if is_rule_present(sg, PORT, my_ip):
        print(f"[INFO] Port {PORT} already open for {my_ip}")
        return

    ec2_client.authorize_security_group_ingress(
        GroupId=SECURITY_GROUP_ID,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": PORT,
                "ToPort": PORT,
                "IpRanges": [{"CidrIp": my_ip}]
            }
        ]
    )

    print(f"[SUCCESS] Port {PORT} opened for {my_ip}")

open_port_if_needed()


