# Pulse Installation Guide

This guide covers installation on macOS, Linux, Docker, and Raspberry Pi.

---

## Prerequisites

**All platforms:**
- Python 3.11 or newer ([download here](https://www.python.org/downloads/))
- OpenClaw installed with webhooks enabled
- Terminal/command line access

**Verify Python version:**
```bash
python3 --version  # Should show 3.11.x or higher
```

---

## Quick Install (Mac/Linux)

```bash
# 1. Clone repository
git clone https://github.com/jcap93/pulse.git
cd pulse

# 2. Install dependencies
pip3 install -r requirements.txt

# 3. Copy example config
cp config/pulse.example.yaml config/pulse.yaml

# 4. Edit config (set your webhook URL + token)
nano config/pulse.yaml  # or use your preferred editor

# 5. Run Pulse
python3 -m pulse

# 6. Verify (in another terminal)
curl http://localhost:9720/health
```

**Expected output:**
```json
{"status": "healthy", "uptime": 42}
```

---

## Detailed Setup by Platform

### macOS

**Option 1: Run manually**
```bash
cd /path/to/pulse
python3 -m pulse
```

**Option 2: Run as LaunchAgent (starts on login)**

1. Create LaunchAgent plist:
```bash
cat > ~/Library/LaunchAgents/ai.iris.pulse.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.iris.pulse</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>-m</string>
        <string>pulse</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/YOUR_USERNAME/pulse</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/YOUR_USERNAME/pulse/pulse.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOUR_USERNAME/pulse/pulse.error.log</string>
</dict>
</plist>
EOF
```

2. Update paths:
```bash
# Replace YOUR_USERNAME with your actual username
sed -i '' 's/YOUR_USERNAME/'"$USER"'/g' ~/Library/LaunchAgents/ai.iris.pulse.plist
```

3. Load and start:
```bash
launchctl load ~/Library/LaunchAgents/ai.iris.pulse.plist
launchctl start ai.iris.pulse
```

4. Verify:
```bash
launchctl list | grep pulse
curl http://localhost:9720/health
```

**To stop:**
```bash
launchctl stop ai.iris.pulse
launchctl unload ~/Library/LaunchAgents/ai.iris.pulse.plist
```

---

### Linux

**Option 1: Run manually**
```bash
cd /path/to/pulse
python3 -m pulse
```

**Option 2: Run as systemd service (starts on boot)**

1. Create service file:
```bash
sudo nano /etc/systemd/system/pulse.service
```

2. Paste this content (update paths):
```ini
[Unit]
Description=Pulse Autonomous Agent Daemon
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/pulse
ExecStart=/usr/bin/python3 -m pulse
Restart=always
RestartSec=10
StandardOutput=append:/home/YOUR_USERNAME/pulse/pulse.log
StandardError=append:/home/YOUR_USERNAME/pulse/pulse.error.log

[Install]
WantedBy=multi-user.target
```

3. Replace YOUR_USERNAME:
```bash
sudo sed -i 's/YOUR_USERNAME/'"$USER"'/g' /etc/systemd/system/pulse.service
```

4. Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable pulse
sudo systemctl start pulse
```

5. Verify:
```bash
sudo systemctl status pulse
curl http://localhost:9720/health
```

**To stop:**
```bash
sudo systemctl stop pulse
sudo systemctl disable pulse
```

---

### Docker

**Why Docker?**
- Portable across machines (easy migration)
- Isolated environment (no dependency conflicts)
- Easy updates (`docker pull` + restart)

**Build image:**
```bash
cd pulse
docker build -t pulse:latest .
```

**Run container:**
```bash
docker run -d \
  --name pulse \
  --restart unless-stopped \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/state:/app/state \
  -p 9720:9720 \
  pulse:latest
```

**Verify:**
```bash
docker logs pulse
curl http://localhost:9720/health
```

**Update:**
```bash
docker stop pulse
docker rm pulse
git pull
docker build -t pulse:latest .
docker run -d ... (same command as above)
```

**Migrate to another machine:**
```bash
# On old machine:
docker save pulse:latest | gzip > pulse-image.tar.gz
tar -czf pulse-data.tar.gz config/ state/

# Copy files to new machine, then:
docker load < pulse-image.tar.gz
tar -xzf pulse-data.tar.gz
docker run -d ... (same command as above)
```

---

### Raspberry Pi

**Recommended:** Pi 4 (4GB+ RAM) or Pi 5

**Install Python 3.11:**
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11
sudo apt install python3.11 python3.11-venv python3-pip -y

# Verify
python3.11 --version
```

**Install Pulse:**
```bash
# Clone
git clone https://github.com/jcap93/pulse.git
cd pulse

# Create virtual environment (recommended for Pi)
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp config/pulse.example.yaml config/pulse.yaml
nano config/pulse.yaml

# Run
python -m pulse
```

**Run as systemd service:**
Follow Linux systemd instructions above, but use:
```ini
ExecStart=/home/YOUR_USERNAME/pulse/venv/bin/python -m pulse
```

**Performance tips:**
- Use `evaluator.mode: "rules"` (avoids AI calls)
- Increase `sensors.filesystem.poll_interval` (reduce CPU)
- Limit `openclaw.max_turns_per_hour` (conserve resources)

---

## Configuration

**Minimal config (config/pulse.yaml):**
```yaml
openclaw:
  webhook_url: "http://localhost:8080/hooks/agent"
  webhook_token: "your-webhook-token-here"
```

**Find your webhook token:**
```bash
cat ~/.openclaw/config.yaml | grep webhookToken
```

**Test configuration:**
```bash
python -m pulse --validate-config
```

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'pulse'"

**Solution:** Install dependencies:
```bash
pip3 install -r requirements.txt
```

### "Connection refused" when curling /health

**Solution:** Pulse isn't running. Check:
```bash
# Manual run
ps aux | grep pulse

# systemd (Linux)
sudo systemctl status pulse

# LaunchAgent (Mac)
launchctl list | grep pulse

# Docker
docker ps | grep pulse
```

### "Webhook failed: 401 Unauthorized"

**Solution:** Wrong webhook token. Update `config/pulse.yaml`:
```yaml
openclaw:
  webhook_token: "correct-token-from-openclaw-config"
```

### High CPU usage on Raspberry Pi

**Solution:** Reduce polling frequency:
```yaml
sensors:
  filesystem:
    poll_interval: 600  # 10 minutes instead of 1
```

### Pulse triggers too often

**Solution:** Increase thresholds and cooldowns:
```yaml
drives:
  trigger_threshold: 8.0  # Higher = less sensitive

openclaw:
  min_trigger_interval: 3600  # 1 hour cooldown
  max_turns_per_hour: 4       # Cap at 4 triggers/hour
```

### Pulse never triggers

**Solution:** Lower threshold or check drive sources exist:
```yaml
drives:
  trigger_threshold: 3.0  # Lower = more sensitive
  
  categories:
    goals:
      sources:
        - "goals.json"  # Make sure this file exists!
```

---

## Next Steps

1. **Read the docs:** `docs/architecture.md` explains how Pulse works
2. **Check examples:** `examples/` has ready-to-use configs
3. **Tune your config:** See `docs/configuration.md` for all options
4. **Monitor behavior:** Check `pulse.log` and `/state` endpoint

---

## Uninstall

**Manual install:**
```bash
rm -rf /path/to/pulse
```

**LaunchAgent (Mac):**
```bash
launchctl unload ~/Library/LaunchAgents/ai.iris.pulse.plist
rm ~/Library/LaunchAgents/ai.iris.pulse.plist
```

**systemd (Linux):**
```bash
sudo systemctl stop pulse
sudo systemctl disable pulse
sudo rm /etc/systemd/system/pulse.service
sudo systemctl daemon-reload
```

**Docker:**
```bash
docker stop pulse
docker rm pulse
docker rmi pulse:latest
```

---

## Support

- **GitHub Issues:** [github.com/jcap93/pulse/issues](https://github.com/jcap93/pulse/issues)
- **Discord:** [OpenClaw community](https://discord.com/invite/clawd) (#pulse channel)
- **Docs:** [docs/](docs/)

---

**Happy automating!** 🔮
