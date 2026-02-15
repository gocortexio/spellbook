# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
#
# GoCortex Spellbook Docker Image
# Provides a ready-to-use environment for building Cortex Platform content packs

FROM python:3.11-alpine

ARG SPELLBOOK_VERSION=1.20.2
LABEL maintainer="GoCortexIO - Simon Sigre"
LABEL description="Cortex Platform content pack builder with demisto-sdk"
LABEL version="${SPELLBOOK_VERSION}"
LABEL org.opencontainers.image.source="https://github.com/gocortexio/spellbook"
LABEL org.opencontainers.image.description="GoCortex Spellbook - Cortex Platform content pack builder with demisto-sdk"
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"

# Install system dependencies
RUN apk add --no-cache \
    git \
    curl \
    jq \
    zip

# Set up application directory
WORKDIR /app

# Install demisto-sdk (pinned version) and additional dependencies
RUN pip install --no-cache-dir "demisto-sdk==1.38.18" "gitpython>=3.1.46" "pyyaml>=6.0.3"

# Copy project files
COPY spellbook/ ./spellbook/
COPY spellbook.py ./

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
