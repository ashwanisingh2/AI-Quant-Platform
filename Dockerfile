# AI Quant Platform — API + CLIs (aiq-api, aiq-engine, aiq-agent, aiq-data)
# Build:  docker build -t ai-quant-api .
# Run:    docker run -p 8000:8000 --env-file .env -v $(pwd)/data:/app/data ai-quant-api
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for pyarrow/nautilus wheels (mostly not needed, but safe)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install the package (+ kite extra for live trading; llm extra optional)
COPY pyproject.toml README.md ./
COPY apps ./apps
COPY libs ./libs
RUN pip install ".[kite]"

# Data (parquet) — mount as volume in production
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000

# Healthcheck — API /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

# Default: orchestration API. Override for CLIs, e.g.:
#   docker run ai-quant-api aiq-engine strategies
CMD ["aiq-api"]
