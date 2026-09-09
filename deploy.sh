#!/bin/bash
set -e

echo "[deploy] Setting up HaggleMind on Oracle VM..."

# Update and install dependencies
sudo apt-get update -qq
sudo apt-get install -y python3-pip python3-venv git curl sqlite3

# Create project directory
mkdir -p ~/hagglemind
cd ~/hagglemind

# Clone the repository
if [ ! -d ".git" ]; then
    git clone https://github.com/cipoklean/hagglemind.git .
else
    git pull origin master
fi

# Setup Python virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt
pip install -q uvicorn requests

# Check if .env exists, create if not
if [ ! -f ".env" ]; then
    cat > .env << 'ENVEOF'
VENDOR_URL=http://localhost:8777
X402_ENABLED=false
BASE_RPC=https://sepolia.base.org
PRIVATE_KEY=
WALLET_ADDRESS=
API_PORT=8000
BASE_CHAIN_ID=84532
GAS_LIMIT=200000
GAS_PRICE_GWEI=1.0
X402_USD_VALUE=0.01
ENVEOF
    echo "[deploy] Created default .env - edit it with your secrets"
fi

# Create systemd service for vendor server
sudo tee /etc/systemd/system/hagglemind-vendor.service > /dev/null << 'SVC'
[Unit]
Description=HaggleMind Vendor Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/hagglemind
ExecStart=/home/ubuntu/hagglemind/venv/bin/python vendor_server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVC

# Create systemd service for API backend
sudo tee /etc/systemd/system/hagglemind-api.service > /dev/null << 'SVC'
[Unit]
Description=HaggleMind FastAPI Backend
After=network.target hagglemind-vendor.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/hagglemind
ExecStart=/home/ubuntu/hagglemind/venv/bin/python -m uvicorn api:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
EnvironmentFile=/home/ubuntu/hagglemind/.env

[Install]
WantedBy=multi-user.target
SVC

# Enable and start services
sudo systemctl daemon-reload
sudo systemctl enable hagglemind-vendor hagglemind-api
sudo systemctl restart hagglemind-vendor hagglemind-api

# Wait for services to be ready
sleep 3

# Verify
echo ""
echo "[deploy] Checking service status..."
systemctl is-active hagglemind-vendor && echo "  ✓ vendor_server.py running" || echo "  ✗ vendor_server.py FAILED"
systemctl is-active hagglemind-api && echo "  ✓ api.py running" || echo "  ✗ api.py FAILED"

echo ""
echo "[deploy] Deployment complete!"
echo "[deploy] Frontend: http://127.0.0.1:5173 (run Vite separately)"
echo "[deploy] API:      http://127.0.0.1:8000"
echo "[deploy] Vendor:   http://127.0.0.1:8777"
echo ""
echo "[deploy] To check logs:"
echo "  journalctl -u hagglemind-api -f"
echo "  journalctl -u hagglemind-vendor -f"
