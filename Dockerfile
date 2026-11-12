# Local Voice Studio - Production Container
# Multi-stage build for minimal final image size

FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

WORKDIR /build

# Copy dependency files
COPY app/backend/requirements.txt ./backend/

# Create virtual environment and install dependencies
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --no-cache -r backend/requirements.txt


# ============================================================
FROM python:3.11-slim AS runtime

# Runtime dependencies (FFmpeg for audio processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy application code (models/, tools/ and data/ are mounted volumes —
# fetch them with `docker compose run --rm voice-studio bash scripts/download_models.sh`)
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY README.md ./

# Create data/model directories
RUN mkdir -p data/voices data/generations data/meta logs models tools

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    VOICE_STUDIO_HOST=0.0.0.0 \
    VOICE_STUDIO_PORT=8200 \
    VOICE_STUDIO_DATA_DIR=/app/data \
    VOICE_STUDIO_MODELS_DIR=/app/models \
    VOICE_STUDIO_MOSS_THREADS=4

# Expose port
EXPOSE 8200

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8200/api/health || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "backend.main:app", "--app-dir", "app", "--host", "0.0.0.0", "--port", "8200"]
