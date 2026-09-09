#!/bin/bash
set -e

echo "[nginx] Setting up HaggleMind Nginx configuration..."

# Create Nginx config
sudo tee /etc/nginx/sites-available/hagglemind > /dev/null << 'EOF'
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
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
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
EOF

# Enable site
sudo ln -sf /etc/nginx/sites-available/hagglemind /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test and reload
sudo nginx -t
sudo systemctl reload nginx

echo ""
echo "[nginx] ✓ Configuration complete!"
echo "[nginx] Frontend URL: http://158.180.57.167"
echo "[nginx] API path: /api/* (proxied to localhost:8000)"
echo ""
echo "Test with:"
echo "  curl http://158.180.57.167/api/health"
