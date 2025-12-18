# iam_setup.py
import boto3
import json
import time

ROLE_NAME = "EC2-Proxy-Role"
PROFILE_NAME = "EC2-Proxy-Profile"

iam = boto3.client("iam")


def create_iam_role_and_profile():
    # -----------------------------
    # Create IAM Role
    # -----------------------------
    try:
        iam.get_role(RoleName=ROLE_NAME)
        print(f"IAM role '{ROLE_NAME}' already exists")
    except iam.exceptions.NoSuchEntityException:
        print(f"Creating IAM role '{ROLE_NAME}'")

        assume_role_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }

        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy)
        )

        iam.attach_role_policy(
            RoleName=ROLE_NAME,
            PolicyArn="arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess"
        )

        time.sleep(10)  # IAM propagation

    # -----------------------------
    # Create Instance Profile
    # -----------------------------
    try:
        iam.get_instance_profile(InstanceProfileName=PROFILE_NAME)
        print(f"Instance profile '{PROFILE_NAME}' already exists")
    except iam.exceptions.NoSuchEntityException:
        print(f"Creating instance profile '{PROFILE_NAME}'")

        iam.create_instance_profile(
            InstanceProfileName=PROFILE_NAME
        )

        iam.add_role_to_instance_profile(
            InstanceProfileName=PROFILE_NAME,
            RoleName=ROLE_NAME
        )

        time.sleep(10)

    print("IAM role and instance profile are ready")


if __name__ == "__main__":
    create_iam_role_and_profile()
