# HaggleMind — Deployment Guide

## Local Development (3 servers)

```bash
# Terminal 1 — Mock vendor server
python vendor_server.py

# Terminal 2 — FastAPI backend
python -m uvicorn api:app --port 8000

# Terminal 3 — Frontend
cd frontend && npm run dev
```

## Oracle Cloud Deployment

### Prerequisites
- Oracle Cloud Always Free VM (Ubuntu 22.04)
- SSH access with private key
- Public IP: `158.180.57.167`

### One-Command Deploy

```bash
# From your local machine:
scp -i ~/.ssh/id_ed25519 /tmp/deploy.sh ubuntu@158.180.57.167:~/
ssh -i ~/.ssh/id_ed25519 ubuntu@158.180.57.167 "bash ~/deploy.sh"
```

### Configure Secrets

Edit `.env` on the VM:

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@158.180.57.167
nano ~/hagglemind/.env
```

Set your values:
```
X402_ENABLED=true
PRIVATE_KEY=0x...
VENDOR_BURNER_WALLET=0x...
BASE_RPC_KEY=your_base_rpc_key  # optional
```

Then restart:
```bash
sudo systemctl restart hagglemind-api
```

### Frontend Deployment

Option A: Host frontend on Vercel (free, no card):
```bash
cd frontend
npx vercel --prod
```
Then set `VITE_API_URL=https://your-backend-url:8000` in Vercel env vars.

Option B: Run Vite on Oracle VM (port 5173):
```bash
cd ~/hagglemind/frontend
npm install
npm run build
# Serve with nginx or simple HTTP server
```

### Management Commands

```bash
# Check status
systemctl status hagglemind-vendor hagglemind-api

# View logs
journalctl -u hagglemind-api -f
journalctl -u hagglemind-vendor -f

# Restart
sudo systemctl restart hagglemind-vendor hagglemind-api

# Stop/Start
sudo systemctl stop/start hagglemind-vendor hagglemind-api
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│   Frontend      │────▶│   Oracle VM     │
│   (Vercel/5173) │     │                 │
└─────────────────┘     │  ┌───────────┐  │
                        │  │ api.py    │  │
                        │  │ (:8000)   │  │
                        │  └─────┬─────┘  │
                        │        │         │
                        │  ┌────▼─────┐   │
                        │  │vendor     │   │
                        │  │server     │   │
                        │  │(:8777)    │   │
                        │  └──────────┘   │
                        │                 │
                        │  ┌───────────┐  │
                        │  │Sibyl      │  │
                        │  │Memory     │  │
                        │  │(SQLite)   │  │
                        │  └──────────┘  │
                        └─────────────────┘
                                │
                                ▼
                        Base Sepolia (x402 payments)
```

## Port Mapping (Oracle Security List)

Ensure these ports are open in Oracle Cloud Network → Security Lists:
- **8000** TCP — FastAPI backend
- **8777** TCP — Vendor mock server  
- **5173** TCP — Vite dev server (optional)

Add ingress rules:
```
Source: 0.0.0.0/0
Protocol: TCP
Port: 8000, 8777, 5173
```
