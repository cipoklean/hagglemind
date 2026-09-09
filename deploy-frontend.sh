#!/bin/bash
set -e

echo "[deploy] Deploying frontend to Oracle VM..."

# Create directory on VM
ssh -i "$SSH_KEY" ubuntu@"$VM_IP" "mkdir -p ~/hagglemind/frontend/dist"

# Copy frontend files
scp -r -i "$SSH_KEY" ~/Desktop/hagglemind/frontend/dist/* ubuntu@"$VM_IP":~/hagglemind/frontend/dist/

# Configure Nginx
sudo tee /etc/nginx/sites-available/hagglemind > /dev/null << 'NGINX'
server {
    listen 80;
    server_name _;
    root /home/ubuntu/hagglemind/frontend/dist;
    index index.html;

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Proxy API requests to backend
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Proxy vendor requests
    location /vendor/ {
        proxy_pass http://127.0.0.1:8777;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Static assets caching
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
NGINX

# Enable site
sudo ln -sf /etc/nginx/sites-available/hagglemind /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

echo "[deploy] Frontend deployed to http://$VM_IP"
echo "[deploy] API proxy: /api/* -> localhost:8000"
echo "[deploy] Vendor proxy: /vendor/* -> localhost:8777"
