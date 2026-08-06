FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /uvx /bin/

# Install Docker CLI (to talk to host docker via mounted socket)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | \
        gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce-cli && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install util-linux for nsenter (usually already present, but be sure)
RUN apt-get update && \
    apt-get install -y --no-install-recommends util-linux && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY server.py dependency_versions.py ./

# Audit log volume
RUN mkdir -p /audit

EXPOSE 8765

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "server.py"]
