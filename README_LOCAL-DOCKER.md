# GoCortex Spellbook - Local Docker Workflow

GoCortex Spellbook is a toolset for building, validating, and packaging Cortex Platform content packs. It solves the problem of creating compliant content packs without needing to understand the intricacies of the demisto-sdk and Cortex Platform schema requirements.

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
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook init my-content --author "Your Organisation"
```

This creates a my-content folder containing:

- Packs directory with a SamplePack to get you started
- spellbook.yaml configuration file
- GitHub Actions workflows (optional)

To skip GitHub Actions (Docker-only workflow):

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook init my-content --author "Your Organisation" --no-ci
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
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook list-packs
```

The SamplePack contains starter templates for common content types including integrations, scripts, playbooks, and Cortex Platform content like modelling rules and parsing rules.

---

## Create a New Pack

[WARNING] Always use the create command to make new packs. Never copy existing packs directly, as this causes naming conflicts during upload.

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook create MyNewPack --description "My new content pack"
```

This creates a properly structured pack with all required metadata files.

---

## Validate

Validation checks your pack against demisto-sdk rules:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook validate MyNewPack
```

To validate all packs at once:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook validate-all
```

---

## Build

Building creates a distributable zip file in the artefacts directory:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook build MyNewPack
```

To build all packs:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook build --all
```

The zip files appear in my-content/artifacts/:

```
my-content/
+-- artifacts/
    +-- MyNewPack-v1.0.0.zip
    +-- SamplePack-v1.0.0.zip
```

---

## Upload

Upload your pack directly to Cortex Platform using the API.

First, set the required environment variables:

```bash
export DEMISTO_BASE_URL="https://your-cortex-instance.xdr.paloaltonetworks.com"
export DEMISTO_API_KEY="your-api-key"
export XSIAM_AUTH_ID="your-auth-id"
```

Then upload:

```bash
# Upload to XSIAM
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  -e DEMISTO_BASE_URL \
  -e DEMISTO_API_KEY \
  -e XSIAM_AUTH_ID \
  ghcr.io/gocortexio/spellbook upload Packs/MyNewPack --xsiam

# Upload to XSOAR (no XSIAM_AUTH_ID or --xsiam flag needed)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  -e DEMISTO_BASE_URL \
  -e DEMISTO_API_KEY \
  ghcr.io/gocortexio/spellbook upload Packs/MyNewPack

# Upload with insecure connection (skip certificate validation)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  -e DEMISTO_BASE_URL \
  -e DEMISTO_API_KEY \
  -e XSIAM_AUTH_ID \
  ghcr.io/gocortexio/spellbook upload Packs/MyNewPack --xsiam --insecure
```

---

## Version Management

Spellbook provides commands for managing pack versions.

Show current version information:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook version MyNewPack
```

Set a specific version:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook set-version MyNewPack 2.0.0

# Set version and create Git tag (stages all pack files)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook set-version MyNewPack 2.0.0 --tag
```

Bump version automatically:

```bash
# Bump revision (1.0.0 -> 1.0.1) - default behaviour
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack

# Bump revision explicitly (1.0.0 -> 1.0.1)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --revision

# Bump minor version (1.0.0 -> 1.1.0)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --minor

# Bump major version (1.0.0 -> 2.0.0)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --major

# Bump version and create a Git tag
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --tag
```

---

## Git Configuration for Tagging

When using the `--tag` flag with `bump-version` or `set-version`, the container needs access to your Git identity to create commits and tags. The `--tag` flag stages all files in the pack directory, commits them, and creates a Git tag. Mount your local git config file:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --tag
```

Use the `--message` or `-m` flag to specify a custom commit message for CI/CD integration (e.g., auto-closing issues):

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --tag -m "Closes #123"
```

The `:ro` suffix mounts the file as read-only for security. Without this mount, you will see the error "Author identity unknown".

---

## Harmless Warnings

The following warnings can be safely ignored during normal operation:

[INFO] "Could not get repository properties: Remote named 'origin' didn't exist"

This message appears when working locally without a Git remote configured. It is expected behaviour for local-only development and does not affect building or validation.

[INFO] "AG100 validation in the pre-commit GitHub Action fails..."

This is informational text about GitHub Actions validation. It does not indicate an error with your local build process.

---

## Summon (Import from Platform)

The summon command imports content exported from the Cortex Platform.

### Importing Correlation Rules

Export correlation rules from XSIAM as JSON, then pipe to the summon command:

```bash
cat exported_rules.json | docker run -i --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook summon correlation MyPack
```

For interactive paste (paste JSON then press Ctrl+D):

```bash
docker run -it --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook summon correlation MyPack
```

The command:
- Parses the JSON array of correlation rules
- Removes platform-specific fields (rule_id, simple_schedule, etc.)
- Adds required fields (global_rule_id, fromversion)
- Creates YAML files in Packs/MyPack/CorrelationRules/

---

## Command Reference

All commands below assume you are in the my-content directory. The standard Docker invocation is:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook <command>
```

Replace `<command>` with any of the following:

| Action | Command |
|--------|---------|
| Initialise instance | init my-content --author "Your Name" |
| Check environment | check-init |
| List instances | list-instances |
| List packs | list-packs |
| Create pack | create PackName |
| Validate pack | validate PackName |
| Validate all | validate-all |
| Build pack | build PackName |
| Build all | build --all |
| Upload pack | upload PackName |
| Upload to XSIAM | upload PackName --xsiam |
| Show version | version PackName |
| Set version | set-version PackName X.Y.Z |
| Bump version | bump-version PackName |
| Bump revision | bump-version PackName --revision |
| Bump minor | bump-version PackName --minor |
| Bump major | bump-version PackName --major |
| Bump and tag | bump-version PackName --tag |
| Bump with message | bump-version PackName --tag -m "Closes #123" |
| Import correlations | summon correlation PackName (with stdin) |
