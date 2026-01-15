# GoCortex Spellbook Docker Image
# Provides a ready-to-use environment for building Cortex Platform content packs

FROM python:3.11-alpine

ARG SPELLBOOK_VERSION=1.18.10
LABEL maintainer="GoCortexIO - Simon Sigre"
LABEL description="Cortex Platform content pack builder with demisto-sdk"
LABEL version="${SPELLBOOK_VERSION}"
LABEL org.opencontainers.image.source="https://github.com/gocortexio/spellbook"
LABEL org.opencontainers.image.description="GoCortex Spellbook - Cortex Platform content pack builder with demisto-sdk"
LABEL org.opencontainers.image.licenses="MIT"

# Install system dependencies
RUN apk add --no-cache \
    git \
    curl \
    jq \
    zip

# Set up application directory
WORKDIR /app

# Install demisto-sdk from latest GitHub release and additional dependencies
RUN LATEST_VERSION=$(curl -s https://api.github.com/repos/demisto/demisto-sdk/releases/latest | jq -r '.tag_name') && \
    pip install --no-cache-dir "demisto-sdk==${LATEST_VERSION#v}" gitpython pyyaml || \
    pip install --no-cache-dir demisto-sdk gitpython pyyaml

# Copy project files
COPY spellbook/ ./spellbook/
COPY spellbook.py ./
COPY spellbook.yaml ./

# Create non-root user for security
RUN addgroup -g 1000 spellbook && \
    adduser -u 1000 -G spellbook -s /bin/sh -D spellbook

# Create mount point for user content with correct ownership
RUN mkdir -p /content && chown -R spellbook:spellbook /app /content

# Suppress demisto-sdk content repository warning (we handle pack structure ourselves)
ENV DEMISTO_SDK_IGNORE_CONTENT_WARNING=true

# Switch to non-root user
USER spellbook

# Set working directory to the mount point for user operations
WORKDIR /content

# Set entrypoint to the spellbook CLI
ENTRYPOINT ["python", "/app/spellbook.py"]
