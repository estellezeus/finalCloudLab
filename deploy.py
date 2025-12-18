import boto3

ec2 = boto3.resource("ec2", region_name="us-east-1")

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



# Create 3 EC2 instances
mysql_db_intances = ec2.create_instances(
    ImageId="ami-0c398cb65a93047f2",  # Ubuntu 22.04 LTS
    InstanceType="t2.micro",
    MinCount=3,
    MaxCount=3,
    KeyName="finalLabKey",
    SecurityGroupIds=["sg-07eb91b8897bb1816"], # this sg opens the port 22 for ssh connexions
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
    SecurityGroupIds=["sg-07eb91b8897bb1816"],
    UserData=large_instance_user_data,
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
    SecurityGroupIds=["sg-07eb91b8897bb1816"],
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


