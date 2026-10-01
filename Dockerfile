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

ARG SPELLBOOK_VERSION=1.25.4
# The commit the image was built from. CI passes it (docker/metadata-action
# already computes the SHA for the OCI label); a plain `docker build` leaves it
# empty, and empty is meaningful - it is how `--version` tells an unstamped
# local build apart from a published one. The label alone cannot do this job:
# labels are daemon-side image metadata and a running container cannot read
# its own, so the value has to be promoted to an ENV to reach the CLI.
ARG VCS_REF=""
ENV SPELLBOOK_REVISION="${VCS_REF}"
LABEL maintainer="GoCortexIO - Simon Sigre"
LABEL description="Cortex Platform content pack builder with demisto-sdk"
LABEL version="${SPELLBOOK_VERSION}"
LABEL org.opencontainers.image.source="https://github.com/gocortexio/spellbook"
LABEL org.opencontainers.image.description="GoCortex Spellbook - Cortex Platform content pack builder with demisto-sdk"
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"
LABEL org.opencontainers.image.revision="${VCS_REF}"

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

# Declare any mounted directory safe for git, at SYSTEM level.
#
# The container runs as uid 1000 while a bind mount is owned by the host user,
# so git refuses a repository created on the host with "detected dubious
# ownership" and every command that shells out to git fails. Content that is NOT
# yet a repository is unaffected, because spellbook inits and owns the throwaway
# one it creates - which is why this only surfaces once the content directory is
# version controlled, and why release tagging makes it certain.
#
# SYSTEM rather than --global, and this is the whole point. The global config
# lives at /home/spellbook/.gitconfig, which is the exact path this project's own
# README tells people to mount their host gitconfig over to supply a committer
# identity. That mount replaced the file holding the fix, so the documented
# invocation silently undid it and bump-version --tag still failed on a 1.24.0
# image. safe.directory is multi-valued, so a mounted global config ADDS to the
# system entry rather than replacing it, and both survive.
#
# Wildcard rather than a named path: the mount path belongs to whoever writes the
# docker run line, and enumerating paths loses one report at a time.
# safe.directory guards against running hooks out of someone else's repository on
# a shared machine, and neither half applies to an ephemeral single-purpose
# container whose only visible repository is the one the user mounted into it.
#
# Runs before USER spellbook because writing /etc/gitconfig needs root.
RUN git config --system --add safe.directory '*'

# Suppress demisto-sdk content repository warning (we handle pack structure ourselves)
ENV DEMISTO_SDK_IGNORE_CONTENT_WARNING=true

# Switch to non-root user
USER spellbook

# Set working directory to the mount point for user operations
WORKDIR /content

# Set entrypoint to the spellbook CLI
ENTRYPOINT ["python", "/app/spellbook.py"]
