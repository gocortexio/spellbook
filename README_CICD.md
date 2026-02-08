# GoCortex Spellbook - CI/CD Workflow

GoCortex Spellbook is a toolset for building, validating, and packaging Cortex Platform content packs. It solves the problem of creating compliant content packs without needing to understand the intricacies of the demisto-sdk and Cortex Platform schema requirements.

This guide walks you through setting up automated builds and validation using GitHub Actions or GitLab CI/CD. Both platforms are supported and can coexist in the same repository.

---

## Prerequisites

- Docker installed locally (for testing)
- GitHub or GitLab repository for your content
- Access to a container registry (GitHub Container Registry, Docker Hub, or similar)

---

## Spellbook Docker Image

The official Spellbook Docker image is published to GitHub Container Registry:

```bash
docker pull ghcr.io/gocortexio/spellbook:latest
```

This image is used by the CI/CD workflows and is automatically built with each release.

---

## Repository Setup

Create a content instance with CI enabled (this is the default):

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook init my-content --author "Your Organisation"
```

Initialise Git and push to GitHub:

```bash
cd my-content
git init
git branch -M main
git add .
git commit -s -m "Initial commit"
git remote add origin git@github.com:your-org/my-content.git
git push -u origin main
```

The -s flag signs your commit, which is required by some organisations.

---

## GitHub Actions Workflows

Your instance includes two workflow files in .github/workflows/:

- conjure.yml - Builds packs when tags are pushed
- validate.yml - Validates packs on pull requests and pushes to main

These workflows are pre-configured to use the official Spellbook image (`ghcr.io/gocortexio/spellbook:latest`). No additional configuration is required.

---

## Tag and Release Flow

The build workflow triggers when you push a tag matching the pattern PackName-vX.Y.Z.

Create a release tag:

```bash
git tag SamplePack-v1.0.0
git push origin SamplePack-v1.0.0
```

This triggers the build workflow which:

1. Checks out your repository
2. Runs Spellbook to build the pack
3. Uploads the zip file as a build artefact
4. Creates a GitHub release with the zip attached

For subsequent releases, increment the version:

```bash
# Set version, stage all pack files, commit and tag in one command
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook set-version SamplePack 1.1.0 --tag

# Push the commit and tag
git push && git push origin SamplePack-v1.1.0
```

---

## Version Bump Commands

Spellbook provides the bump-version command to automatically increment pack versions:

```bash
# Bump revision (1.0.0 -> 1.0.1) - default behaviour
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version SamplePack

# Bump revision explicitly (1.0.0 -> 1.0.1)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version SamplePack --revision

# Bump minor version (1.0.0 -> 1.1.0)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version SamplePack --minor

# Bump major version (1.0.0 -> 2.0.0)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version SamplePack --major

# Bump version and create a Git tag for CI/CD triggering
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version SamplePack --tag

# Bump with custom commit message (for auto-closing issues)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version SamplePack --tag -m "Closes #123"
```

The --tag flag creates a Git tag in the format PackName-vX.Y.Z which triggers the build workflow automatically. Use --message or -m to specify a custom commit message for CI/CD integration (e.g., auto-closing issues). Mounting your git config allows the container to use your Git identity for commits and tags.

---

## Optional: PR Validation Enhancements

The default validate.yml workflow runs basic validation. You can enhance it with additional checks.

Add a check for naming consistency by editing .github/workflows/validate.yml:

```yaml
      - name: Check content naming
        run: |
          for pack in Packs/*/; do
            pack_name=$(basename "$pack")
            docker run --rm \
              -v ${{ github.workspace }}/Packs:/content/Packs \
              -v ${{ github.workspace }}/spellbook.yaml:/content/spellbook.yaml \
              ghcr.io/gocortexio/spellbook:latest \
              check-naming "$pack_name"
          done
```

---

## GitLab CI/CD Pipelines

Your instance also includes a .gitlab-ci.yml file for GitLab CI/CD. This provides equivalent functionality to the GitHub Actions workflows.

### Pipeline Stages

The GitLab pipeline has three stages:

1. validate - Runs on merge requests and pushes to main/master when Packs/ changes
2. build - Runs when tags matching *-v* are pushed or on manual trigger
3. release - Creates a GitLab release with artefacts attached

### GitLab Variables

The pipeline uses these predefined GitLab CI/CD variables:

- CI_PROJECT_DIR - The directory where the repository is cloned
- CI_COMMIT_TAG - The tag name when a tag is pushed
- CI_MERGE_REQUEST_ID - Set when running on a merge request
- CI_COMMIT_BRANCH - The branch name
- CI_PIPELINE_SOURCE - How the pipeline was triggered (push, web, etc.)

### Manual Pipeline Trigger

To manually trigger a build in GitLab:

1. Go to CI/CD > Pipelines in your project
2. Click "Run pipeline"
3. Select the branch or tag to build
4. Click "Run pipeline"

### GitLab Container Registry

To use GitLab Container Registry instead of GitHub Container Registry, update the image reference in .gitlab-ci.yml:

```yaml
ghcr.io/gocortexio/spellbook:latest
```

Replace with your own registry if you host a copy of the Spellbook image.

### Docker-in-Docker Requirements

The GitLab pipeline uses Docker-in-Docker (dind) to run containers. Your GitLab Runner must be configured with:

- Docker executor
- Privileged mode enabled

If your runner does not support privileged mode, consider using a shell executor or Kubernetes executor with appropriate permissions.

---

## Uploading Packs to Cortex Platform

Spellbook can upload content packs directly to your Cortex Platform instance using the upload command.

### Required Environment Variables

The upload command requires credentials to authenticate with your Cortex instance:

- DEMISTO_BASE_URL - Your Cortex Platform instance URL
- DEMISTO_API_KEY - API key with Instance Administrator role
- XSIAM_AUTH_ID - Authentication ID (required for XSIAM only)

### Upload Examples

Upload a pack directory to XSOAR:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  -e DEMISTO_BASE_URL="https://your-instance.demisto.com" \
  -e DEMISTO_API_KEY="your-api-key" \
  ghcr.io/gocortexio/spellbook upload Packs/SamplePack
```

Upload to XSIAM (requires auth ID and --xsiam flag):

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  -e DEMISTO_BASE_URL="https://your-instance.xdr.paloaltonetworks.com" \
  -e DEMISTO_API_KEY="your-api-key" \
  -e XSIAM_AUTH_ID="your-auth-id" \
  ghcr.io/gocortexio/spellbook upload Packs/SamplePack --xsiam
```

Upload with insecure connection (skip certificate validation):

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  -e DEMISTO_BASE_URL="https://your-instance.xdr.paloaltonetworks.com" \
  -e DEMISTO_API_KEY="your-api-key" \
  -e XSIAM_AUTH_ID="your-auth-id" \
  ghcr.io/gocortexio/spellbook upload Packs/SamplePack --xsiam --insecure
```

### Using an Environment File

To avoid typing credentials each time, store them in a .env file:

```bash
# .env (this file is automatically excluded from Git)
DEMISTO_BASE_URL=https://your-instance.xdr.paloaltonetworks.com
DEMISTO_API_KEY=your-api-key
XSIAM_AUTH_ID=your-auth-id
```

Then use --env-file to load the credentials:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  --env-file .env \
  ghcr.io/gocortexio/spellbook upload Packs/SamplePack --xsiam
```

The .env file is included in .gitignore by default to prevent accidental commits of credentials.

### Upload Options

- --xsiam - Upload to XSIAM (requires XSIAM_AUTH_ID)
- --insecure - Skip SSL certificate verification
- --skip-validation - Skip pack validation before upload

---

## Troubleshooting

[ERROR] Workflow fails with "image not found"

The Spellbook Docker image is not accessible to the GitHub Actions runner. Check that:

- The image was pushed to the registry
- The image path in the workflow file matches exactly
- For private registries, the repository has access configured

[ERROR] Workflow fails with "permission denied" on volume mounts

The Spellbook container runs as a non-root user (UID 1000) for security. The GitHub Actions runner uses a different UID (typically 1001), causing permission mismatches when writing to mounted volumes.

The solution is to run the container as the same user as the runner:

```yaml
- name: Build packs
  run: |
    mkdir -p artifacts
    docker run --rm --user $(id -u):$(id -g) \
      -v ${{ github.workspace }}/Packs:/content/Packs \
      -v ${{ github.workspace }}/artifacts:/content/artifacts \
      -v ${{ github.workspace }}/spellbook.yaml:/content/spellbook.yaml \
      ghcr.io/gocortexio/spellbook:latest \
      build --all --no-validate
```

The --user flag ensures the container process runs with the same UID/GID as the runner, allowing it to write to directories created by the runner.

Also ensure your workflow uses ${{ github.workspace }} for volume mounts:

```yaml
-v ${{ github.workspace }}/Packs:/content/Packs
```

[ERROR] Build succeeds but release is not created

The release job only runs for tag pushes. Check that:

- Your tag matches the expected pattern (PackName-vX.Y.Z)
- The tag was pushed to origin, not just created locally

[ERROR] Validation fails with "not a git repository"

The checkout step must include fetch-depth: 0 for demisto-sdk to work correctly:

```yaml
- name: Checkout repository
  uses: actions/checkout@v4
  with:
    fetch-depth: 0
```

[INFO] "Could not get repository properties: Remote named 'origin' didn't exist"

This warning can be safely ignored. It appears because demisto-sdk expects a specific Git remote configuration that may differ in CI environments.

[ERROR] Tag push does not trigger the workflow

Check that your tag matches the pattern in conjure.yml:

```yaml
on:
  push:
    tags:
      - '*-v*'
```

Tags must contain "-v" to trigger the workflow (for example, SamplePack-v1.0.0).

---

## Workflow Files Reference

conjure.yml triggers:

- Push of tags matching *-v* pattern
- Manual workflow dispatch with optional pack name

validate.yml triggers:

- Pull requests that modify files in Packs/
- Pushes to main or master branches that modify files in Packs/
