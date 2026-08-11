FROM python:3.14-slim

WORKDIR /app/pulse

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source — the repo IS the pulse package
COPY src/ src/
COPY config/ config/
COPY bin/ bin/
COPY pyproject.toml .

# State volume — mount this for persistence across restarts
VOLUME /root/.pulse

# Config volume — mount your pulse.yaml here
VOLUME /app/pulse/config

# PYTHONPATH makes `pulse.src` importable from /app
ENV PYTHONPATH=/app
CMD ["python", "-m", "pulse.src"]
