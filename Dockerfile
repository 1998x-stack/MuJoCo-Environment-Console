FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MUJOCO_GL=osmesa \
    PYOPENGL_PLATFORM=osmesa \
    CONSOLE_ENV_ROOT=/app/envs \
    CONSOLE_DATA_ROOT=/app/data \
    PYTHONPATH=/app:/app/envs \
    HOME=/tmp \
    PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip ca-certificates curl \
      libosmesa6 libgl1 libegl1 libglfw3 libglew2.2 libglib2.0-0 \
      libx11-6 libxext6 libxrender1 libsm6 git \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv
WORKDIR /app
COPY requirements.txt requirements-robotics.txt ./
# CPU PyTorch avoids downloading CUDA wheels on a headless Ubuntu server.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch==2.9.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt
ARG INSTALL_ROBOTICS=1
RUN if [ "$INSTALL_ROBOTICS" = "1" ]; then pip install --no-cache-dir -r requirements-robotics.txt; fi
COPY app ./app
COPY envs ./envs
COPY scripts ./scripts
RUN mkdir -p /app/data/runs
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s --retries=3 CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
