# GoCortex Spellbook - Local Docker Workflow

This guide walks you through building Cortex Platform content packs using Docker on your local machine.

---

## Prerequisites

- Docker installed and running

---

## Get Spellbook

Pull the pre-built image from GitHub Container Registry (preferred):

```bash
docker pull ghcr.io/gocortexio/spellbook:latest
```

All commands in this guide use the registry image. If you prefer to build locally:

```bash
git clone <spellbook-repo-url>
cd gocortex-spellbook
docker build -t ghcr.io/gocortexio/spellbook .
```

---

## Create a Content Instance

Run this command from the directory where you want your content instance created:

```bash
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook init my-content --author "Your Organisation"
```

This creates a my-content folder containing:

- Packs directory with a SamplePack to get you started
- spellbook.yaml configuration file
- GitHub Actions workflows (optional)

To skip GitHub Actions (Docker-only workflow):

```bash
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook init my-content --author "Your Organisation" --no-ci
```

---

## Initialise Git

A Git repository with at least one commit is required for demisto-sdk validation to work.

```bash
cd my-content
git init
git branch -M main
git add .
git commit -s -m "Initial commit"
```

If using a remote repository (optional):

```bash
git remote add origin <your-repo-url>
git push -u origin main
```

---

## Explore SamplePack

Your instance includes a SamplePack with example content. List the available packs:

```bash
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook list-packs
```

The SamplePack contains starter templates for common content types including integrations, scripts, playbooks, and Cortex Platform content like modelling rules and parsing rules.

---

## Create a New Pack

[WARNING] Always use the create command to make new packs. Never copy existing packs directly, as this causes naming conflicts during upload.

```bash
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook create MyNewPack --description "My new content pack"
```

This creates a properly structured pack with all required metadata files.

---

## Rename Content (If Copying From Other Packs)

If you have copied content items from another pack, the internal names will not match your pack name. This causes upload failures. Fix this by running:

```bash
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook rename-content MyNewPack
```

This command updates all content item names and IDs to match your pack name.

---

## Validate

Validation checks your pack against demisto-sdk rules:

```bash
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook validate MyNewPack
```

To validate all packs at once:

```bash
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook validate-all
```

---

## Lint (Optional)

Linting runs additional code quality checks using demisto-sdk pre-commit hooks:

```bash
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook lint MyNewPack
```

This step is optional but recommended before uploading to production systems.

---

## Build

Building creates a distributable zip file in the artefacts directory:

```bash
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook build MyNewPack
```

To build all packs:

```bash
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook build --all
```

The zip files appear in my-content/artifacts/:

```
my-content/
+-- artifacts/
    +-- MyNewPack-1.0.0.zip
    +-- SamplePack-1.0.0.zip
```

---

## Upload

Upload your pack directly to Cortex Platform using the API.

First, set the required environment variables:

```bash
# For Cortex Platform 6.x
export DEMISTO_BASE_URL="https://your-cortex-instance.com"
export DEMISTO_API_KEY="your-api-key"

# For Cortex Platform 8.x (also set auth ID)
export XSIAM_AUTH_ID="your-auth-id"
```

Then upload:

```bash
# Upload to Cortex Platform
docker run --rm -v $(pwd):/content \
  -e DEMISTO_BASE_URL \
  -e DEMISTO_API_KEY \
  -e XSIAM_AUTH_ID \
  ghcr.io/gocortexio/spellbook upload Packs/MyNewPack --zip --xsiam

# Upload a pre-built zip file
docker run --rm -v $(pwd):/content \
  -e DEMISTO_BASE_URL \
  -e DEMISTO_API_KEY \
  -e XSIAM_AUTH_ID \
  ghcr.io/gocortexio/spellbook upload artifacts/MyNewPack-1.0.0.zip

# Upload with insecure connection (skip certificate validation)
docker run --rm -v $(pwd):/content \
  -e DEMISTO_BASE_URL \
  -e DEMISTO_API_KEY \
  ghcr.io/gocortexio/spellbook upload artifacts/MyNewPack-1.0.0.zip --insecure
```

---

## Version Management

Spellbook provides commands for managing pack versions.

Show current version information:

```bash
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook version MyNewPack
```

Set a specific version:

```bash
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook set-version MyNewPack 2.0.0
```

Bump version automatically:

```bash
# Bump revision (1.0.0 -> 1.0.1) - default behaviour
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version MyNewPack

# Bump revision explicitly (1.0.0 -> 1.0.1)
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version MyNewPack --revision

# Bump minor version (1.0.0 -> 1.1.0)
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version MyNewPack --minor

# Bump major version (1.0.0 -> 2.0.0)
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version MyNewPack --major

# Bump version and create a Git tag
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version MyNewPack --tag
```

---

## Harmless Warnings

The following warnings can be safely ignored during normal operation:

[INFO] "Could not get repository properties: Remote named 'origin' didn't exist"

This message appears when working locally without a Git remote configured. It is expected behaviour for local-only development and does not affect building or validation.

[INFO] "AG100 validation in the pre-commit GitHub Action fails..."

This is informational text about GitHub Actions validation. It does not indicate an error with your local build process.

---

## Command Reference

All commands below assume you are in the my-content directory:

| Action | Command |
|--------|---------|
| List packs | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook list-packs |
| Create pack | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook create PackName |
| Rename content | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook rename-content PackName |
| Validate pack | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook validate PackName |
| Validate all | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook validate-all |
| Lint pack | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook lint PackName |
| Build pack | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook build PackName |
| Build all | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook build --all |
| Show version | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook version PackName |
| Set version | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook set-version PackName X.Y.Z |
| Bump version | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version PackName |
| Bump revision | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version PackName --revision |
| Bump minor | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version PackName --minor |
| Bump major | docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version PackName --major |
