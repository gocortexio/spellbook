# GoCortex Spellbook - CI/CD Workflow

This guide walks you through setting up automated builds and validation using GitHub Actions.

---

## Prerequisites

- Docker installed locally (for testing)
- GitHub repository for your content
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
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook init my-content --author "Your Organisation"
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

Note: The -s flag signs your commit, which is required by some organisations.

---

## GitHub Actions Workflows

Your instance includes two workflow files in .github/workflows/:

- build.yml - Builds packs when tags are pushed
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
# Update the pack version first
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook set-version SamplePack 1.1.0

# Commit the version change
git add Packs/SamplePack/pack_metadata.json
git commit -s -m "Bump SamplePack to 1.1.0"
git push

# Create and push the tag
git tag SamplePack-v1.1.0
git push origin SamplePack-v1.1.0
```

---

## Version Bump Commands

Spellbook provides the bump-version command to automatically increment pack versions:

```bash
# Bump revision (1.0.0 -> 1.0.1) - default behaviour
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version SamplePack

# Bump revision explicitly (1.0.0 -> 1.0.1)
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version SamplePack --revision

# Bump minor version (1.0.0 -> 1.1.0)
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version SamplePack --minor

# Bump major version (1.0.0 -> 2.0.0)
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version SamplePack --major

# Bump version and create a Git tag for CI/CD triggering
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook bump-version SamplePack --tag
```

The --tag flag creates a Git tag in the format PackName-vX.Y.Z which triggers the build workflow automatically.

---

## Optional: PR Validation Enhancements

The default validate.yml workflow runs basic validation. You can enhance it with additional checks.

Add linting to pull request validation by editing .github/workflows/validate.yml:

```yaml
jobs:
  validate:
    name: Validate Packs
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Validate packs
        run: |
          docker run --rm \
            -v ${{ github.workspace }}/Packs:/content/Packs \
            -v ${{ github.workspace }}/spellbook.yaml:/content/spellbook.yaml \
            ghcr.io/gocortexio/spellbook:latest \
            validate-all

      - name: Lint packs
        run: |
          for pack in Packs/*/; do
            pack_name=$(basename "$pack")
            docker run --rm \
              -v ${{ github.workspace }}/Packs:/content/Packs \
              -v ${{ github.workspace }}/spellbook.yaml:/content/spellbook.yaml \
              ghcr.io/gocortexio/spellbook:latest \
              lint "$pack_name"
          done
```

Add a check for naming consistency:

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

## Troubleshooting

[ERROR] Workflow fails with "image not found"

The Spellbook Docker image is not accessible to the GitHub Actions runner. Check that:

- The image was pushed to the registry successfully
- The image path in the workflow file matches exactly
- For private registries, the repository has access configured

[ERROR] Workflow fails with "permission denied" on volume mounts

GitHub Actions uses specific paths. Ensure your workflow uses ${{ github.workspace }} for volume mounts:

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

Check that your tag matches the pattern in build.yml:

```yaml
on:
  push:
    tags:
      - '*-v*'
```

Tags must contain "-v" to trigger the workflow (for example, SamplePack-v1.0.0).

---

## Workflow Files Reference

build.yml triggers:

- Push of tags matching *-v* pattern
- Manual workflow dispatch with optional pack name

validate.yml triggers:

- Pull requests that modify files in Packs/
- Pushes to main or master branches that modify files in Packs/
