# Docker Deployment Guide

Complete guide for running Pulse in Docker — from local development to production.

---

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/astra-ventures/pulse.git
cd pulse

# 2. Copy environment file
cp .env.example .env
nano .env  # Add your OPENCLAW_HOOKS_TOKEN

# 3. Build and run
docker-compose up -d

# 4. Verify
docker logs pulse
curl http://localhost:9720/health
```

---

## Configuration

### Environment Variables

Create `.env` file (copy from `.env.example`):

```bash
OPENCLAW_HOOKS_TOKEN=your-webhook-token-here
```

Get your webhook token:
```bash
cat ~/.openclaw/config.yaml | grep webhookToken
```

### Pulse Configuration

Edit `config/pulse.yaml` before building:

```yaml
openclaw:
  webhook_url: "http://host.docker.internal:8080/hooks/agent"
  webhook_token: "${OPENCLAW_HOOKS_TOKEN}"  # Reads from .env
```

**Note:** `host.docker.internal` allows container to reach OpenClaw on host machine.

---

## Docker Compose (Recommended)

**File:** `docker-compose.yml`

```yaml
version: "3.8"

services:
  pulse:
    build: .
    container_name: pulse
    restart: unless-stopped
    volumes:
      - pulse-state:/root/.pulse        # Persistent state
      - ./config:/app/config:ro         # Read-only config
    environment:
      - OPENCLAW_HOOKS_TOKEN=${OPENCLAW_HOOKS_TOKEN}
    ports:
      - "9720:9720"                     # API port
    extra_hosts:
      - "host.docker.internal:host-gateway"  # Host access
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  pulse-state:  # Named volume for state persistence
```

**Commands:**

```bash
# Start
docker-compose up -d

# Stop
docker-compose down

# Restart
docker-compose restart

# View logs
docker-compose logs -f

# Update (rebuild after git pull)
docker-compose down
git pull
docker-compose up -d --build
```

---

## Standalone Docker

**Build image:**
```bash
docker build -t pulse:0.2.3 .
```

**Run container:**
```bash
docker run -d \
  --name pulse \
  --restart unless-stopped \
  -v pulse-state:/root/.pulse \
  -v $(pwd)/config:/app/config:ro \
  -e OPENCLAW_HOOKS_TOKEN=your-token-here \
  -p 9720:9720 \
  --add-host host.docker.internal:host-gateway \
  pulse:0.2.3
```

**Verify:**
```bash
docker logs pulse
curl http://localhost:9720/health
```

---

## Volume Management

### State Persistence

Pulse stores state in `/root/.pulse/` inside container. Mount this as a volume:

```bash
# Named volume (recommended)
-v pulse-state:/root/.pulse

# Or bind mount (explicit path)
-v /path/on/host/.pulse:/root/.pulse
```

**Inspect state:**
```bash
# Via API
curl http://localhost:9720/state

# Direct file access
docker exec pulse cat /root/.pulse/drives.json
```

**Backup state:**
```bash
# Named volume backup
docker run --rm \
  -v pulse-state:/source \
  -v $(pwd):/backup \
  alpine tar czf /backup/pulse-state-backup.tar.gz -C /source .

# Restore
docker run --rm \
  -v pulse-state:/target \
  -v $(pwd):/backup \
  alpine tar xzf /backup/pulse-state-backup.tar.gz -C /target
```

### Configuration

Mount `config/` as read-only:

```bash
-v $(pwd)/config:/app/config:ro
```

**Update config without restart:**

1. Edit `config/pulse.yaml` on host
2. Restart container: `docker restart pulse`

(Future: Hot-reload via API `/config` endpoint)

---

## Networking

### Access OpenClaw on Host

Docker Compose handles this automatically via `extra_hosts`.

**Manual setup:**
```bash
--add-host host.docker.internal:host-gateway
```

Then in `config/pulse.yaml`:
```yaml
openclaw:
  webhook_url: "http://host.docker.internal:8080/hooks/agent"
```

### Access OpenClaw on Another Machine

```yaml
openclaw:
  webhook_url: "http://192.168.1.100:8080/hooks/agent"
```

Replace with actual IP/hostname of OpenClaw machine.

### Access Pulse API from Host

Port 9720 is exposed:
```bash
curl http://localhost:9720/health
```

### Access from Other Containers

```yaml
# docker-compose.yml
services:
  pulse:
    # ...
  
  dashboard:
    # ...
    environment:
      - PULSE_URL=http://pulse:9720
```

---

## Multi-Architecture Builds

**Build for multiple platforms (Apple Silicon + Intel):**

```bash
# Enable buildx (once)
docker buildx create --use

# Build multi-arch
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t yourorg/pulse:0.2.3 \
  --push \
  .
```

**Pull on any platform:**
```bash
docker pull yourorg/pulse:0.2.3
```

---

## Production Best Practices

### 1. Use specific version tags

```yaml
services:
  pulse:
    image: yourorg/pulse:0.2.3  # Not :latest
```

### 2. Limit resources

```yaml
services:
  pulse:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.1'
          memory: 128M
```

### 3. Health checks

```yaml
services:
  pulse:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9720/health"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 10s
```

### 4. Logging

Already configured in docker-compose.yml:
```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
```

**View logs:**
```bash
docker logs pulse --tail 100 -f
```

### 5. Secrets management

**Don't hardcode tokens!** Use environment variables:

```bash
# .env (gitignored)
OPENCLAW_HOOKS_TOKEN=secret-token-here

# docker-compose.yml
environment:
  - OPENCLAW_HOOKS_TOKEN=${OPENCLAW_HOOKS_TOKEN}
```

**Or Docker secrets (Swarm mode):**
```yaml
services:
  pulse:
    secrets:
      - openclaw_token
    environment:
      - OPENCLAW_HOOKS_TOKEN_FILE=/run/secrets/openclaw_token

secrets:
  openclaw_token:
    external: true
```

---

## Migration Between Hosts

**Export from old machine:**
```bash
# Stop Pulse
docker-compose down

# Export state
docker run --rm \
  -v pulse-state:/source \
  -v $(pwd):/backup \
  alpine tar czf /backup/pulse-state.tar.gz -C /source .

# Copy files to new machine:
# - pulse-state.tar.gz
# - config/pulse.yaml
# - .env
```

**Import on new machine:**
```bash
# Clone repo
git clone https://github.com/astra-ventures/pulse.git
cd pulse

# Restore config
cp /path/to/pulse.yaml config/
cp /path/to/.env .

# Restore state
docker volume create pulse-state
docker run --rm \
  -v pulse-state:/target \
  -v $(pwd):/backup \
  alpine tar xzf /backup/pulse-state.tar.gz -C /target

# Start
docker-compose up -d
```

---

## Troubleshooting

### Container won't start

**Check logs:**
```bash
docker logs pulse
```

**Common issues:**
- Missing `.env` file → copy from `.env.example`
- Invalid `config/pulse.yaml` → validate with `python -m pulse --validate-config` (run locally first)
- Port 9720 already in use → change in docker-compose.yml

### Can't reach OpenClaw webhook

**Test from inside container:**
```bash
docker exec pulse curl -v http://host.docker.internal:8080/hooks/agent
```

**If fails:**
- OpenClaw not running → start OpenClaw first
- Firewall blocking → allow port 8080
- Wrong host → use actual IP instead of `host.docker.internal`

### State not persisting

**Verify volume is mounted:**
```bash
docker inspect pulse | grep Mounts -A 10
```

Should show:
```json
"Mounts": [
  {
    "Type": "volume",
    "Name": "pulse-state",
    "Source": "/var/lib/docker/volumes/pulse-state/_data",
    "Destination": "/root/.pulse"
  }
]
```

### High memory usage

**Check actual usage:**
```bash
docker stats pulse
```

**Reduce by:**
- Lowering `max_turns_per_hour` in config
- Using `evaluator.mode: "rules"` (no AI calls)
- Increasing `sensors.filesystem.poll_interval`

---

## Docker Hub Publishing (For Maintainers)

**Build and push:**
```bash
# Login
docker login

# Build multi-arch
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t yourorg/pulse:0.2.3 \
  -t yourorg/pulse:latest \
  --push \
  .

# Tag and push
docker tag pulse:0.2.3 yourorg/pulse:0.2.3
docker push yourorg/pulse:0.2.3
docker push yourorg/pulse:latest
```

**Users can then:**
```bash
docker pull yourorg/pulse:0.2.3
docker run -d ... yourorg/pulse:0.2.3
```

---

## Alternative: Podman

Pulse works with Podman (rootless Docker alternative):

```bash
# Replace 'docker' with 'podman'
podman build -t pulse:0.2.3 .
podman run -d ... pulse:0.2.3

# Or with podman-compose
podman-compose up -d
```

---

## Next Steps

- **Monitoring:** See `docs/deployment.md` for Prometheus integration
- **Scaling:** Run multiple Pulse instances with different configs (different agents)
- **Orchestration:** Deploy with Kubernetes (see `examples/k8s/` - coming soon)

---

## Support

- **GitHub Issues:** [github.com/astra-ventures/pulse/issues](https://github.com/astra-ventures/pulse/issues)
- **Discord:** [OpenClaw community](https://discord.com/invite/clawd) (#pulse channel)

---

**Happy containerizing!** 🐳
