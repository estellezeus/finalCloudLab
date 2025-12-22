#!/bin/bash

echo "==== Deploying the instances ===="
python deploy.py

sleep 10

echo "==== Configuring replication on the MySql intances ===="
python configure-replication.py

sleep 10

echo "==== Benchmarking the proxy ===="
python benchmark.py

sleep 10

echo "==== Benchmarking the gatekeeper ===="
python benchmark_gatekeeper.py

sleep 10

echo "==== Cleaning up ===="
python cleanup.py

echo "==== Done !!! ===="