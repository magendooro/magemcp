# =============================================================================
# MageMCP — Multi-stage Docker build
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — install dependencies and build the package
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies (hatchling needs these)
RUN pip install --no-cache-dir hatchling

# Copy build metadata first for better layer caching.
# pyproject.toml changes less often than source code.
# README.md is required by hatchling (referenced in pyproject.toml).
COPY pyproject.toml README.md ./

# Copy source code
COPY src/ src/

# Install the package (production deps only) into /install prefix
RUN pip install --no-cache-dir --prefix=/install .

# ---------------------------------------------------------------------------
# Stage 2: Runtime — minimal image with only what's needed to run
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Create non-root user for security
RUN groupadd --system magemcp && \
    useradd --system --gid magemcp --create-home magemcp

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Environment defaults — only non-secret values
ENV MAGEMCP_LOG_LEVEL=INFO \
    MAGENTO_STORE_CODE=default
# MAGENTO_BASE_URL and MAGENTO_TOKEN must be provided at runtime (secrets)

# Switch to non-root user
USER magemcp
WORKDIR /home/magemcp

# NOTE: MageMCP currently uses stdio transport, which has no HTTP endpoint
# for healthchecks. When HTTP/SSE transport is added, a HEALTHCHECK
# instruction should be added here, e.g.:
#   HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["magemcp"]
