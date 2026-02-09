#!/bin/bash

# Test_ai Project Execution Script - DevOps Edition
set -e 

echo "--- Initializing System Dependencies ---"

# 1. Update and Install System Packages
sudo apt update -y 
sudo apt install python3 python3-venv python3-pip docker.io -y 

# 2. Fix Docker Permissions
# Add current user to docker group if not already there
if ! groups $USER | grep &>/dev/null "\bdocker\b"; then
    echo "Adding $USER to the docker group..."
    sudo usermod -aG docker $USER
    echo "Note: Group changes may require a logout/login to take effect fully."
    echo "Applying group change for this session..."
    # This allows the script to continue without a logout
    exec sg docker "$0"
fi

# 3. Check for Prerequisites
command -v python3 >/dev/null 2>&1 || { echo "Python 3 failed. Aborting." >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Docker failed. Aborting." >&2; exit 1; }

# 4. Set up Virtual Environment and Dependencies
echo "Setting up virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

echo "Installing project dependencies..."
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    pip install temporalio docker python-dotenv
fi

# 5. Handle Temporal Server (Docker)
echo "Checking Temporal Server..."
# Using sudo here ensures it runs even if the group change hasn't propagated to the kernel yet
if ! sudo docker ps -a -q -f name=temporal-admin | grep -q . ; then
    echo "Starting new Temporal container..."
    sudo docker run -d --name temporal-admin -p 7233:7233 -p 8233:8233 temporalio/admin-tools:latest
else
    if ! sudo docker ps -q -f name=temporal-admin | grep -q . ; then
        echo "Restarting existing Temporal container..."
        sudo docker start temporal-admin
    else
        echo "Temporal container is already running."
    fi
fi

# 6. Prepare Environment Variables
# Adding root and src to PYTHONPATH to fix import errors
export PYTHONPATH=$PYTHONPATH:$(pwd):$(pwd)/src

# Load TEMPORAL_HOST from .env if it exists
if [ -f .env ]; then
    TEMPORAL_HOST=$(grep TEMPORAL_HOST .env | cut -d '=' -f2 | tr -d '\r')
fi
TEMPORAL_HOST=${TEMPORAL_HOST:-"localhost:7233"}
echo "Targeting Temporal Host: $TEMPORAL_HOST"

# 7. Execution Menu
echo "------------------------------------------------"
echo "Select an option to run:"
echo "1) Start Worker (Processes tasks)"
echo "2) Start Client (Trigger tasks)"
echo "3) Run Both (Worker in background, then Client)"
echo "q) Quit"
echo "------------------------------------------------"
read -p "Choice [1-3]: " choice

case $choice in
    1)
        python3 worker.py
        ;;
    2)
        python3 client.py
        ;;
    3)
        python3 worker.py &
        WORKER_PID=$!
        echo "Waiting 5s for worker to start..."
        sleep 5
        python3 client.py
        kill $WORKER_PID
        ;;
    q)
        exit 0
        ;;
    *)
        echo "Invalid choice."
        ;;
esac
