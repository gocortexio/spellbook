# GoCortex Spellbook Docker Image
# Provides a ready-to-use environment for building Cortex Platform content packs

FROM python:3.11-slim-bookworm

LABEL maintainer="GoCortex Spellbook Contributors"
LABEL description="Cortex Platform content pack builder with demisto-sdk"
LABEL version="1.16.1"
LABEL org.opencontainers.image.source="https://github.com/gocortexio/spellbook"
LABEL org.opencontainers.image.description="GoCortex Spellbook - Cortex Platform content pack builder with demisto-sdk"
LABEL org.opencontainers.image.licenses="MIT"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    jq \
    zip \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Set up application directory
WORKDIR /app

# Install demisto-sdk from latest GitHub release
RUN LATEST_VERSION=$(curl -s https://api.github.com/repos/demisto/demisto-sdk/releases/latest | jq -r '.tag_name') && \
    pip install --no-cache-dir "demisto-sdk==${LATEST_VERSION#v}" || \
    pip install --no-cache-dir demisto-sdk

# Install additional Python dependencies
RUN pip install --no-cache-dir \
    gitpython \
    pyyaml \
    click

# Copy project files
COPY spellbook/ ./spellbook/
COPY spellbook.py ./
COPY spellbook.yaml ./

# Create mount point for user content
RUN mkdir -p /content

# Suppress demisto-sdk content repository warning (we handle pack structure ourselves)
ENV DEMISTO_SDK_IGNORE_CONTENT_WARNING=true

# Set working directory to the mount point for user operations
WORKDIR /content

# Set entrypoint to the spellbook CLI
ENTRYPOINT ["python", "/app/spellbook.py"]
