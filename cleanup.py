import boto3

ec2 = boto3.resource("ec2", region_name="us-east-1")

# Filtrer les instances par tag Role
instances = ec2.instances.filter(
    Filters=[
        {"Name": "tag:Role", "Values": ["manager", "worker", "gateway", "proxy"]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopped"]}
    ]
)

instance_ids = [instance.id for instance in instances]

if instance_ids:
    print("Deleting instances:", instance_ids)
    ec2.instances.filter(InstanceIds=instance_ids).terminate()
else:
    print("No instances found")
