#!/bin/bash
# Polly Connect EC2 Setup Script
# Run on a fresh Amazon Linux 2023 t2.micro instance
#
# Usage: ssh ec2-user@<IP> 'bash -s' < setup_ec2.sh
set -e

echo "=== Polly Connect EC2 Setup ==="

# Update system
sudo dnf update -y
sudo dnf install -y python3.11 python3.11-pip git

# Create app directory
sudo mkdir -p /opt/polly-connect
sudo chown ec2-user:ec2-user /opt/polly-connect

# Clone repo
cd /opt/polly-connect
if [ ! -d ".git" ]; then
    git clone https://github.com/Glen-collab/polly-connect.git .
else
    git pull origin master
fi

# Install Python dependencies
pip3.11 install -r server/requirements.txt

# Create data directory if needed
mkdir -p data

# Copy data files if they don't exist in data/
if [ ! -f "data/jokes.json" ]; then
    cp jokes.js data/jokes.json 2>/dev/null || true
    cp questions.js data/questions.json 2>/dev/null || true
    cp polly-config.js data/polly-config.json 2>/dev/null || true
fi

# Create systemd service
sudo cp deploy/polly-connect.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable polly-connect

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Edit environment variables in /etc/systemd/system/polly-connect.service"
echo "2. Start the service: sudo systemctl start polly-connect"
echo "3. Check logs: sudo journalctl -u polly-connect -f"
echo ""
echo "Make sure your EC2 instance has an IAM role with:"
echo "  - AmazonPollyFullAccess"
echo "  - AmazonTranscribeFullAccess"
echo "  - AmazonS3FullAccess (or scoped to polly-connect-data bucket)"
