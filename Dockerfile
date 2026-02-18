FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY pulse/ pulse/
COPY config/ config/

RUN pip install --no-cache-dir .

# State volume — mount this for persistence across restarts
VOLUME /root/.pulse

# Config volume — mount your pulse.yaml here
VOLUME /app/config

CMD ["python", "-m", "pulse"]
