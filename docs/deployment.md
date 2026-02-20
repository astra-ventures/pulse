# Pulse Deployment Guide

Get Pulse running in production — from localhost testing to 24/7 cloud deployment.

---

## Table of Contents

1. [Local Development](#local-development)
2. [Production Setup](#production-setup)
3. [Docker Deployment](#docker-deployment)
4. [Systemd Service (Linux)](#systemd-service-linux)
5. [LaunchAgent (macOS)](#launchagent-macos)
6. [Cloud Deployment](#cloud-deployment)
7. [Monitoring](#monitoring)
8. [Troubleshooting](#troubleshooting)

---

## Local Development

### Prerequisites

- Python 3.11+
- OpenClaw installed and configured
- Webhook enabled in OpenClaw config

### Install

```bash
# Clone or install
git clone https://github.com/yourusername/pulse.git
cd pulse

# Install dependencies
pip install -r requirements.txt

# Or via pip (when published)
pip install pulse-agent
```

### Configure

```bash
# Copy example config
cp config/pulse.example.yaml config/pulse.yaml

# Edit required fields
nano config/pulse.yaml
```

**Minimum required:**
```yaml
openclaw:
  webhook_url: "http://localhost:8080/hooks/agent"
  webhook_token: "your-webhook-token"  # from OpenClaw gateway config

workspace:
  root: "/Users/you/.openclaw/workspace"
```

### Run

```bash
# Foreground (for testing)
python -m pulse

# Or use the helper script
./bin/run.sh
```

**Check it's working:**
```bash
# In another terminal
curl http://localhost:9720/health

# Should return:
# {"status": "healthy", "uptime": 123, ...}
```

### Test a Trigger

```bash
# Manually spike a drive
python -m pulse spike goals 5.0 "Testing manual trigger"

# Watch the logs — should trigger an agent turn within 30s
```

---

## Production Setup

### 1. Create Dedicated User (Linux)

```bash
sudo useradd -r -m -s /bin/bash pulse
sudo su - pulse
```

### 2. Install in User Directory

```bash
cd ~
git clone https://github.com/yourusername/pulse.git
cd pulse
pip install --user -r requirements.txt
```

### 3. Configure for Production

```bash
cp config/pulse.example.yaml ~/.pulse/config.yaml
nano ~/.pulse/config.yaml
```

**Production config recommendations:**
```yaml
daemon:
  loop_interval_seconds: 30
  log_level: "INFO"  # not DEBUG (too verbose)

logging:
  output: "/var/log/pulse/pulse.log"  # or ~/pulse/logs/pulse.log
  format: "structured"  # JSON for log aggregation

openclaw:
  min_trigger_interval: 1800  # 30 min cooldown
  max_turns_per_hour: 10      # rate limit

drives:
  trigger_threshold: 5.0
```

### 4. Set Environment Variables

```bash
# Add to ~/.bashrc or ~/.profile
export PULSE_HOOK_TOKEN="your-secret-token"
export PULSE_CONFIG=~/.pulse/config.yaml
export PULSE_STATE_DIR=~/.pulse
```

### 5. Test Before Daemonizing

```bash
python -m pulse
# Let it run for 5 minutes, watch for errors
# Ctrl+C to stop
```

---

## Docker Deployment

### Build

```bash
docker build -t pulse:latest .
```

### Run

```bash
docker run -d \
  --name pulse \
  --restart unless-stopped \
  -e PULSE_HOOK_TOKEN=your-token \
  -v ~/.pulse:/root/.pulse \
  -v /path/to/openclaw/workspace:/workspace:ro \
  -p 9720:9720 \
  pulse:latest
```

**What this does:**
- `-d` — run in background
- `--restart unless-stopped` — auto-restart on crash
- `-e PULSE_HOOK_TOKEN` — pass webhook token
- `-v ~/.pulse:/root/.pulse` — persist state
- `-v /workspace:/workspace:ro` — mount workspace read-only
- `-p 9720:9720` — expose health endpoint

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  pulse:
    build: .
    container_name: pulse
    restart: unless-stopped
    environment:
      - PULSE_HOOK_TOKEN=${PULSE_HOOK_TOKEN}
    volumes:
      - ~/.pulse:/root/.pulse
      - /path/to/openclaw/workspace:/workspace:ro
    ports:
      - "9720:9720"
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

```bash
# Start
docker-compose up -d

# Logs
docker-compose logs -f pulse

# Stop
docker-compose down
```

---

## Systemd Service (Linux)

Create `/etc/systemd/system/pulse.service`:

```ini
[Unit]
Description=Pulse — Autonomous cognition engine for OpenClaw
After=network.target

[Service]
Type=simple
User=pulse
Group=pulse
WorkingDirectory=/home/pulse/pulse
Environment="PULSE_HOOK_TOKEN=your-token"
Environment="PULSE_CONFIG=/home/pulse/.pulse/config.yaml"
ExecStart=/usr/bin/python3 -m pulse
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/pulse/.pulse

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable pulse
sudo systemctl start pulse
```

**Monitor:**
```bash
# Status
sudo systemctl status pulse

# Logs
sudo journalctl -u pulse -f

# Restart
sudo systemctl restart pulse
```

---

## LaunchAgent (macOS)

Create `~/Library/LaunchAgents/ai.openclaw.pulse.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.openclaw.pulse</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>-m</string>
        <string>pulse</string>
    </array>
    
    <key>EnvironmentVariables</key>
    <dict>
        <key>PULSE_HOOK_TOKEN</key>
        <string>your-token</string>
        <key>PULSE_CONFIG</key>
        <string>/Users/you/.pulse/config.yaml</string>
    </dict>
    
    <key>WorkingDirectory</key>
    <string>/Users/you/pulse</string>
    
    <key>StandardOutPath</key>
    <string>/Users/you/.pulse/logs/pulse.log</string>
    
    <key>StandardErrorPath</key>
    <string>/Users/you/.pulse/logs/pulse-error.log</string>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    
    <key>ThrottleInterval</key>
    <integer>60</integer>
</dict>
</plist>
```

**Load and start:**
```bash
# Create log directory
mkdir -p ~/.pulse/logs

# Load the agent
launchctl load ~/Library/LaunchAgents/ai.openclaw.pulse.plist

# Check status
launchctl list | grep pulse

# View logs
tail -f ~/.pulse/logs/pulse.log
```

**Unload (to stop):**
```bash
launchctl unload ~/Library/LaunchAgents/ai.openclaw.pulse.plist
```

---

## Cloud Deployment

### VPS (DigitalOcean, Linode, AWS EC2)

**Requirements:**
- 512 MB RAM minimum (1 GB recommended)
- 5 GB disk
- Ubuntu 22.04 or Debian 11+

**Setup:**
```bash
# SSH into VPS
ssh root@your-vps-ip

# Install dependencies
apt update && apt upgrade -y
apt install -y python3 python3-pip git

# Create pulse user
useradd -r -m -s /bin/bash pulse
su - pulse

# Install Pulse
git clone https://github.com/yourusername/pulse.git
cd pulse
pip3 install --user -r requirements.txt

# Configure
cp config/pulse.example.yaml ~/.pulse/config.yaml
nano ~/.pulse/config.yaml

# Set webhook URL to OpenClaw instance
# If OpenClaw is on the same machine: http://localhost:8080/hooks/agent
# If remote: https://your-openclaw.example.com/hooks/agent

# Test
python3 -m pulse
```

**Daemonize with systemd** (see above).

### Fly.io (Serverless-ish)

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Launch
fly launch
# Follow prompts, select smallest machine (256 MB)

# Set secrets
fly secrets set PULSE_HOOK_TOKEN=your-token

# Deploy
fly deploy
```

**Note:** Pulse needs persistent storage for state. Add a volume:
```bash
fly volumes create pulse_state --size 1
```

Update `fly.toml`:
```toml
[mounts]
  source = "pulse_state"
  destination = "/root/.pulse"
```

---

## Monitoring

### Health Endpoint

```bash
curl http://localhost:9720/health
```

**Response:**
```json
{
  "status": "healthy",
  "uptime": 3600,
  "version": "0.2.3",
  "triggers": {
    "total": 12,
    "last": {
      "timestamp": 1708234567,
      "reason": "goals pressure 6.2",
      "success": true
    }
  },
  "drives": {
    "goals": {"pressure": 2.1, "weight": 1.0},
    "curiosity": {"pressure": 1.3, "weight": 0.8}
  },
  "rate_limit": {
    "turns_last_hour": 3,
    "max_per_hour": 10,
    "cooldown_remaining": 0
  }
}
```

### Prometheus Metrics (Future)

Pulse will expose `/metrics` endpoint with:
- `pulse_uptime_seconds`
- `pulse_triggers_total`
- `pulse_drive_pressure{drive="goals"}`
- `pulse_evaluation_duration_seconds`

---

## Troubleshooting

### Pulse won't start

```bash
# Check config validity
python -m pulse validate

# Check PID lock
rm ~/.pulse/pulse.pid

# Check logs
tail -f ~/.pulse/logs/pulse.log
```

### Agent not receiving triggers

**1. Check webhook reachability:**
```bash
curl -X POST http://localhost:8080/hooks/agent \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{"message": "Test"}'
```

**2. Check OpenClaw webhook config:**
```yaml
# In OpenClaw gateway config
hooks:
  enabled: true
  routes:
    - path: "/hooks/agent"
      token: "your-token"
```

**3. Check Pulse logs for errors:**
```bash
grep "webhook" ~/.pulse/logs/pulse.log
```

### Drives not decaying after triggers

**Check feedback:**
```bash
# After a trigger, agent should send:
curl -X POST http://localhost:9720/feedback \
  -H "Content-Type: application/json" \
  -d '{"drives_addressed": ["goals"], "outcome": "success"}'

# Check Pulse received it:
grep "feedback" ~/.pulse/logs/pulse.log
```

### Too many triggers

**Lower sensitivity:**
```yaml
drives:
  trigger_threshold: 7.0  # was 5.0
  pressure_rate: 0.005    # was 0.01

openclaw:
  min_trigger_interval: 3600  # 1 hour cooldown
```

### Not enough triggers

**Increase sensitivity:**
```yaml
drives:
  trigger_threshold: 3.0
  pressure_rate: 0.02

openclaw:
  min_trigger_interval: 900  # 15 min cooldown
```

### High memory usage

```bash
# Check Python process
ps aux | grep pulse

# If > 200 MB, possible memory leak
# Check for large state files:
ls -lh ~/.pulse/
```

**Prune history:**
```yaml
state:
  max_history_entries: 100  # was 1000
```

### Filesystem sensor missing changes

**Check watchdog:**
```bash
pip show watchdog
# Should be >= 2.0.0
```

**Increase debounce:**
```yaml
sensors:
  filesystem:
    debounce_seconds: 5.0  # was 2.0
```

---

## Migration Between Machines

```bash
# On old machine
tar czf pulse-backup.tar.gz ~/.pulse/

# Copy to new machine
scp pulse-backup.tar.gz newhost:~/

# On new machine
tar xzf pulse-backup.tar.gz -C ~/

# Update webhook URL
nano ~/.pulse/config.yaml
# Change openclaw.webhook_url if needed

# Start
python -m pulse
```

Your agent picks up exactly where it left off.

---

## Security Checklist

- [ ] Webhook token is secret (not in git)
- [ ] Health endpoint not exposed to internet (or firewall port 9720)
- [ ] Pulse runs as non-root user
- [ ] State directory has restrictive permissions (`chmod 700 ~/.pulse`)
- [ ] Logs don't contain secrets
- [ ] Rate limits configured (`max_turns_per_hour`)
- [ ] Guardrails enabled (default)

---

## Next Steps

- [Architecture](architecture.md) — understand how it works
- [Configuration](configuration.md) — tuning reference
- [Examples](../examples/) — sample configs for different use cases
