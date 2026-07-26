# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
#
# GoCortex Spellbook Docker Image
# Provides a ready-to-use environment for building Cortex Platform content packs

# Stage 1: export the pinned dependency set from uv.lock so the image is
# built from the same resolved versions the repository was tested against,
# rather than whatever pip would resolve on the day of the build.
FROM python:3.11-alpine AS requirements

COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /usr/local/bin/uv

WORKDIR /build
COPY pyproject.toml uv.lock ./
COPY spellbook/__init__.py spellbook/__init__.py
RUN uv export --frozen --no-dev --no-emit-project \
    --format requirements-txt -o /build/requirements.lock.txt

# Stage 2: runtime image
FROM python:3.11-alpine

ARG SPELLBOOK_VERSION=1.23.0
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

# Install dependencies (including demisto-sdk) from the exported lock file
COPY --from=requirements /build/requirements.lock.txt ./requirements.lock.txt
RUN pip install --no-cache-dir -r requirements.lock.txt \
    && rm requirements.lock.txt

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
