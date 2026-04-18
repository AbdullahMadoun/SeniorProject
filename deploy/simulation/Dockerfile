FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SKYLINK_API_CPU_CORE=0 \
    SKYLINK_MISSION_API_PORT=8625 \
    SKYLINK_PX4_REF=v1.14.3

WORKDIR /opt/skylink2

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    dos2unix \
    git \
    iproute2 \
    jq \
    lsb-release \
    net-tools \
    python3 \
    python3-pip \
    python3-venv \
    rsync \
    sudo \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY autonomy ./autonomy
COPY deploy/simulation ./deploy/simulation
COPY artifacts/dashboard ./artifacts/dashboard
COPY artifacts/planner ./artifacts/planner

RUN mkdir -p \
      artifacts/generated_worlds \
      artifacts/live_px4 \
      artifacts/px4_bootstrap \
      artifacts/remote_jobs \
      artifacts/replay_bundle/latest \
      artifacts/showcase/latest \
      artifacts/sitl_logs \
    && dos2unix deploy/simulation/*.sh \
    && chmod +x deploy/simulation/bootstrap_remote.sh deploy/simulation/docker_entrypoint.sh \
    && bash deploy/simulation/bootstrap_remote.sh bootstrap

EXPOSE 8625

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8625/api/constraints').read()"

ENTRYPOINT ["bash", "deploy/simulation/docker_entrypoint.sh"]
