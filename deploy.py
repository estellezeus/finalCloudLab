import boto3

ec2 = boto3.resource("ec2", region_name="us-east-1")

# User data script to install MySQL on Ubuntu
user_data_mysql = """#!/bin/bash
apt update -y
apt install -y mysql-server
systemctl enable mysql
systemctl start mysql
"""

# Create 3 EC2 instances
mysql_db_intances = ec2.create_instances(
    ImageId="ami-0c398cb65a93047f2",  # Ubuntu 22.04 LTS
    InstanceType="t2.micro",
    MinCount=3,
    MaxCount=3,
    KeyName="finalLabKey",
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