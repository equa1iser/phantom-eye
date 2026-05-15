FROM python:3.11-slim-bookworm

# OpenCV headless runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps in a separate layer so they're cached on code-only changes
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional: build with --build-arg YOLO=true to include ultralytics (~500 MB)
ARG YOLO=false
RUN if [ "$YOLO" = "true" ]; then pip install --no-cache-dir ultralytics; fi

COPY server/ .

EXPOSE 5000

CMD ["python", "server.py"]
