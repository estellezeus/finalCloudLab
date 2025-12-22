import boto3
import paramiko
import time

REGION = "us-east-1"
KEY_PATH = "cloud_key.pem"
SSH_USER = "ubuntu"

# Lire les IDs
with open("mysql_instance_ids.txt") as f:
    instance_ids = [line.strip() for line in f.readlines()]

source_id = instance_ids[0]
replica_ids = instance_ids[1:]

ec2 = boto3.client("ec2", region_name=REGION)


def get_public_ip(instance_id):
    print("==== Getting instances public addresses ====")
    return ec2.describe_instances(
        InstanceIds=[instance_id]
    )["Reservations"][0]["Instances"][0]["PublicIpAddress"]


source_ip = get_public_ip(source_id)
replica_ips = [get_public_ip(i) for i in replica_ids]

def run_ssh_commands(ip, commands):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ip, username=SSH_USER, key_filename=KEY_PATH)

    for cmd in commands:
        stdin, stdout, stderr = ssh.exec_command(cmd)
        stdout.channel.recv_exit_status()

    ssh.close()

# ------------------------
# Config SOURCE (GTID)
# ------------------------
source_commands = [
    "sudo sed -i '/\\[mysqld\\]/a server-id=1' /etc/mysql/mysql.conf.d/mysqld.cnf",
    "sudo sed -i '/\\[mysqld\\]/a log_bin=mysql-bin' /etc/mysql/mysql.conf.d/mysqld.cnf",
    "sudo sed -i '/\\[mysqld\\]/a binlog_format=ROW' /etc/mysql/mysql.conf.d/mysqld.cnf",
    "sudo sed -i '/\\[mysqld\\]/a gtid_mode=ON' /etc/mysql/mysql.conf.d/mysqld.cnf",
    "sudo sed -i '/\\[mysqld\\]/a enforce_gtid_consistency=ON' /etc/mysql/mysql.conf.d/mysqld.cnf",
    "sudo sed -i '/\\[mysqld\\]/a log_slave_updates=ON' /etc/mysql/mysql.conf.d/mysqld.cnf",
    "sudo systemctl restart mysql",
    "sudo mysql -e \"CREATE USER IF NOT EXISTS 'estelle'@'%' IDENTIFIED BY 'estelle';\"",
    "sudo mysql -e \"GRANT REPLICATION SLAVE ON *.* TO 'estelle'@'%';\"",
    "sudo mysql -e \"FLUSH PRIVILEGES;\""
]

def wait_for_ssh(ip, timeout=180):
    import socket, time
    start = time.time()
    while time.time() - start < timeout:
        try:
            sock = socket.create_connection((ip, 22), timeout=5)
            sock.close()
            return
        except Exception:
            time.sleep(5)
    raise TimeoutError(f"SSH not available on {ip}")

wait_for_ssh(source_ip)

print("==== Running configuration commands on the source ====")
run_ssh_commands(source_ip, source_commands)

time.sleep(10)

# ------------------------
#  Config REPLICAS
# ------------------------
for idx, ip in enumerate(replica_ips, start=2):
    replica_commands = [
        f"sudo sed -i '/\\[mysqld\\]/a server-id={idx}' /etc/mysql/mysql.conf.d/mysqld.cnf",
        "sudo sed -i '/\\[mysqld\\]/a relay-log=relay-bin' /etc/mysql/mysql.conf.d/mysqld.cnf",
        "sudo sed -i '/\\[mysqld\\]/a gtid_mode=ON' /etc/mysql/mysql.conf.d/mysqld.cnf",
        "sudo sed -i '/\\[mysqld\\]/a enforce_gtid_consistency=ON' /etc/mysql/mysql.conf.d/mysqld.cnf",
        "sudo sed -i '/\\[mysqld\\]/a log_slave_updates=ON' /etc/mysql/mysql.conf.d/mysqld.cnf",
        "sudo systemctl restart mysql",
        "sudo mysql -e \"STOP SLAVE;\"",
        "sudo mysql -e \"RESET SLAVE ALL;\"",
        f"sudo mysql -e \"CHANGE MASTER TO MASTER_HOST='{source_ip}', "
        "MASTER_USER='estelle', MASTER_PASSWORD='estelle', MASTER_AUTO_POSITION=1;\"",
        "sudo mysql -e \"START SLAVE;\""
    ]

    print(f"==== Running configuration commands on the replica{idx} ====")

    run_ssh_commands(ip, replica_commands)

print("GTID replication configured successfully")
