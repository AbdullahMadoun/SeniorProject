FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG INSTALL_VLM=true
ARG ENSEMBLE_MEMBERS=""
ARG YOLO12_REPO_URL=""
ARG YOLO12_REPO_REF=""

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/skylink-model-server/.cache/huggingface

WORKDIR /opt/skylink-model-server

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    ca-certificates \
    ffmpeg \
    libsm6 \
    libxext6 \
    libglib2.0-0 \
 && ln -sf /usr/bin/python3 /usr/local/bin/python \
 && ln -sf /usr/bin/pip3 /usr/local/bin/pip \
 && rm -rf /var/lib/apt/lists/*

COPY model_server /opt/skylink-model-server/model_server
COPY external /opt/skylink-model-server/external
COPY patch_yolo12_flash_fallback.py /opt/skylink-model-server/patch_yolo12_flash_fallback.py

RUN python3 -m pip install --upgrade pip wheel "setuptools<82" \
 && if [ "$INSTALL_VLM" = "true" ]; then \
      python3 -m pip install -r /opt/skylink-model-server/model_server/requirements.txt; \
    else \
      python3 -m pip install -r /opt/skylink-model-server/model_server/requirements-yolo.txt; \
    fi \
 && if printf ',%s,' "$ENSEMBLE_MEMBERS" | grep -q ',rezzzq_yolo12s_rdd2022,'; then \
      repo_dir=/opt/skylink-model-server/external/yolov12; \
      if [ ! -f "$repo_dir/ultralytics/nn/modules/block.py" ]; then \
        if [ -z "$YOLO12_REPO_URL" ]; then \
          echo "YOLO12 fork is required for the rezzzq ensemble member." >&2; \
          exit 1; \
        fi; \
        rm -rf "$repo_dir"; \
        git clone "$YOLO12_REPO_URL" "$repo_dir"; \
      fi; \
      if [ -n "$YOLO12_REPO_REF" ] && [ -d "$repo_dir/.git" ]; then \
        git -C "$repo_dir" fetch --all --tags || true; \
        git -C "$repo_dir" checkout "$YOLO12_REPO_REF"; \
      fi; \
      if [ -f "$repo_dir/requirements.txt" ]; then \
        sed -i 's|.*flash_attn.*\\.whl.*|# removed local wheel - using runtime patch instead|' "$repo_dir/requirements.txt" || true; \
      fi; \
      python3 /opt/skylink-model-server/patch_yolo12_flash_fallback.py "$repo_dir"; \
      python3 -m pip install -e "$repo_dir"; \
    fi

RUN mkdir -p \
    /opt/skylink-model-server/runtime \
    /opt/skylink-model-server/.cache/huggingface \
    /opt/skylink-model-server/model_server/models \
 && chmod +x /opt/skylink-model-server/model_server/run.sh

EXPOSE 17612

CMD ["/opt/skylink-model-server/model_server/run.sh"]
