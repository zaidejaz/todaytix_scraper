#!/bin/bash

set -e  # Exit on error

echo "🔧 Deploying Flask App..."

# Ensure .env exists
if [ ! -f "/home/$USER/todaytix_scraper/.env" ]; then
    echo "❌ ERROR: .env file is missing. Create it and rerun the script."
    exit 1
fi

# Load environment variables from .env
set -a
source "/home/$USER/todaytix_scraper/.env"
set +a

# Ensure DOMAIN and EMAIL are set in .env
if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo "❌ ERROR: DOMAIN or EMAIL not set in .env file. Please provide valid values."
    exit 1
fi

echo "🌍 Domain: $DOMAIN"
echo "📧 Email: $EMAIL"

# Step 1: Update System & Install Dependencies
echo "📦 Installing necessary packages..."
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx python3-pip python3-venv

# Step 2: Install Poetry for Dependency Management
echo "📦 Installing Poetry..."
curl -sSL https://install.python-poetry.org | python3 -

# Step 3: Create Virtual Environment for the Flask App
echo "🌱 Creating a virtual environment for the app..."
python3 -m venv /home/$USER/todaytix_scraper/venv
source /home/$USER/todaytix_scraper/venv/bin/activate

# Step 4: Install Flask app dependencies using Poetry
echo "📦 Installing Flask app dependencies..."
cd "/home/$USER/todaytix_scraper"
poetry install --no-dev --no-interaction --no-ansi

# Step 5: Create necessary data directories
echo "📂 Creating necessary data directories..."
mkdir /home/$USER/todaytix_scraper/data/output

# Step 6: Install Gunicorn and Gevent (for concurrency)
echo "📦 Installing Gunicorn and Gevent..."
poetry add gunicorn gevent

# Step 7: Run Flask App using Gunicorn
echo "🚀 Starting Flask app using Gunicorn..."
nohup poetry run gunicorn --workers=6 --worker-class=gevent --worker-connections=1000 \
  --max-requests=10000 --max-requests-jitter=1000 --backlog=2048 --bind 127.0.0.1:5000 \
  --timeout=30 --access-logfile=- --error-logfile=- proxy_manager:create_app() &

# Step 8: Configure NGINX for the Flask App
echo "🔧 Configuring NGINX..."
sudo mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled

NGINX_CONF="/etc/nginx/sites-available/todaytix_scraper"
sudo tee "$NGINX_CONF" > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}

server {
    listen 443 ssl;
    server_name $DOMAIN;

    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF

# Enable NGINX Config
echo "✅ Enabling NGINX configuration..."
sudo ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/
sudo systemctl restart nginx || sudo systemctl start nginx

# Step 9: Install SSL with Certbot
echo "🔐 Setting up SSL with Certbot..."
if ! sudo certbot --nginx -d "$DOMAIN" --email "$EMAIL" --non-interactive --agree-tos; then
    echo "❌ ERROR: Certbot failed to obtain SSL certificates."
    exit 1
fi

# Step 10: Verify SSL and Restart NGINX
echo "✅ SSL Certificates obtained. Restarting NGINX..."
sudo nginx -t
sudo systemctl restart nginx

# Step 11: Auto-renew SSL
echo "⏳ Setting up SSL auto-renew..."
echo "0 0 * * * certbot renew --quiet" | sudo tee -a /etc/crontab

echo "✅ Deployment Completed! Visit https://$DOMAIN"
