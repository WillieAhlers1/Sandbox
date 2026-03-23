# Cloud Build Operations

## Docker Image Hierarchy

Every pipeline produces three Docker images, built in strict order because each layer depends on the previous one:

```
Tier 0:  base-python              (shared foundation: Python 3.12 + uv)
           |
Tier 1:  {pipeline}--base         (framework + pipeline deps, used for training/component execution)
           |
Tier 1:  {pipeline}--serve        (extends --base, adds FastAPI + serving app code)
```

### Tier 0: base-python

- **Dockerfile:** `docker/base/base-python/Dockerfile`
- **Contents:** `python:3.12-slim`, `uv` package manager, system build tools
- **Rebuild frequency:** Rare (Python version upgrades, system package changes)
- **Build script:** `scripts/docker_build_base.sh`

### Tier 1: {pipeline}--base

- **Dockerfile:** `docker/pipelines/{pipeline}/base.Dockerfile`
- **Contents:** `pyproject.toml` + `uv.lock` dependency install, framework code, pipeline code
- **Accepts:** `ARG BASE_IMAGE` pointing to the Tier 0 image
- **Used by:** All KFP component containers (training, evaluation, registration, etc.)

### Tier 1: {pipeline}--serve

- **Dockerfile:** `docker/pipelines/{pipeline}/serve.Dockerfile`
- **Contents:** FastAPI, uvicorn, serving app code (`app/{pipeline}/`)
- **Accepts:** `ARG BASE_IMAGE` pointing to the Tier 1 `--base` image
- **Used by:** Vertex AI Model Registry for online prediction endpoints

## Image Naming Convention

Image names are derived by `NamingConvention.docker_image_name()` in `gcp_ml_framework/naming.py`. This is the single source of truth -- both Python and bash delegate to it.

**Format:** `{pipeline}--{stem}`

- `pipeline` = pipeline directory name, slugified (underscores become hyphens)
- `stem` = Dockerfile filename without `.Dockerfile`
- `--` (double hyphen) is the delimiter between pipeline and stem

**Examples:**

| Dockerfile path | Image name |
|----------------|------------|
| `docker/base/base-python/Dockerfile` | `base-python` |
| `docker/pipelines/house_price/base.Dockerfile` | `house-price--base` |
| `docker/pipelines/house_price/serve.Dockerfile` | `house-price--serve` |

## Image Tagging

**Format:** `{branch}-{short_sha}`

Tags are derived by `NamingConvention.image_tag()` and the equivalent bash logic in `docker_build.sh`:

```
branch slug:   feature/my-work  -->  feature-my-work
short SHA:     a1b2c3d
final tag:     feature-my-work-a1b2c3d
```

Every build produces two tags per image:
- **`:latest`** -- used as the cache source for subsequent builds
- **`:{branch}-{sha}`** -- immutable tag for traceability and rollback

Never use `:latest` for deployments. The `{branch}-{sha}` tag ties every running container to an exact commit.

## cloudbuild.yaml Step-by-Step

The `cloudbuild.yaml` at project root orchestrates all three tiers in a single Cloud Build submission.

**Substitution variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `_TAG` | Image tag (`{branch}-{sha}`) | `latest` |
| `_PIPELINE` | Slugified pipeline name (e.g., `house-price`) | `house-price` |
| `_PIPELINE_DIR` | Pipeline directory name (e.g., `house_price`) | `house_price` |
| `_AR_REPO` | Full AR repo path (`{host}/{project}/{repo}`) | (empty) |

**Steps:**

| Step | Action | Details |
|------|--------|---------|
| 0 | Pull cached `base-python:latest` | `|| true` so first build doesn't fail |
| 1 | Build `base-python` | Tags `:latest` + `:{_TAG}`, uses `--cache-from :latest` |
| 2 | Push `base-python` (both tags) | `--all-tags` |
| 3 | Pull cached `{pipeline}--base:latest` | `|| true` |
| 4 | Build `{pipeline}--base` | `BASE_IMAGE` = freshly built `base-python:{_TAG}`, context = `.` (project root) |
| 5 | Push `{pipeline}--base` (both tags) | |
| 6 | Pull cached `{pipeline}--serve:latest` | `|| true` |
| 7 | Build `{pipeline}--serve` | `BASE_IMAGE` = freshly built `{pipeline}--base:{_TAG}`, context = `.` (project root) |
| 8 | Push `{pipeline}--serve` (both tags) | |

**Build options:**
- Machine type: `E2_HIGHCPU_8` (8 vCPUs for faster builds)
- Logging: `CLOUD_LOGGING_ONLY` (no GCS bucket needed for logs)

**Invocation:**

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions _TAG=main-a1b2c3d,_PIPELINE=house-price,_PIPELINE_DIR=house_price,_AR_REPO=us-east4-docker.pkg.dev/my-project/mlplatform-second-run
```

Or via the CLI:

```bash
UV_ENV_FILE=.env uv run -- gml build training_pipeline
```

## Cache Strategy

Each tier follows the same pattern:

1. **Pull** the `:latest` tag of the target image (ignore failure on first build)
2. **Build** with `--cache-from` pointing to that `:latest` image
3. **Tag** with both `:latest` and `:{branch}-{sha}`
4. **Push** all tags

This means:
- Subsequent builds reuse Docker layer cache from the last successful build
- The `:{branch}-{sha}` tag is immutable and traceable
- `:latest` is always the most recently built image (used only for caching)

**Layer optimization in base.Dockerfile:**

Dependencies are copied and installed before application code:
```dockerfile
COPY pyproject.toml uv.lock .python-version README.md /app/
RUN uv sync --all-groups --all-extras --frozen
COPY gcp_ml_framework/ /app/gcp_ml_framework/
```

If only application code changes, the `uv sync` layer is cached.

## Required IAM Roles

The Cloud Build service account (`{project-number}@cloudbuild.gserviceaccount.com`) needs:

| Role | Purpose |
|------|---------|
| `roles/artifactregistry.writer` | Push Docker images to Artifact Registry |
| `roles/storage.objectAdmin` | Read/write GCS buckets (pipeline artifacts, DAGs) |
| `roles/logging.logWriter` | Write build logs to Cloud Logging |

**Grant roles:**

```bash
PROJECT_ID="your-project-id"
CB_SA="${PROJECT_ID}@cloudbuild.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/storage.objectAdmin"
```

**The user submitting builds** also needs `roles/cloudbuild.builds.editor`.

In production environments, Terraform manages IAM. These manual commands are for dev/sandbox setup.

## Local Build Script

`scripts/docker_build.sh` builds pipeline images locally using Docker. It assumes `base-python:latest` already exists (built via `scripts/docker_build_base.sh`).

**Usage:**

```bash
# Build base-python first (one-time or when base Dockerfile changes)
./scripts/docker_build_base.sh

# Build all pipeline images locally
./scripts/docker_build.sh

# Build a specific pipeline
./scripts/docker_build.sh --pipeline house_price

# Build and push to Artifact Registry
./scripts/docker_build.sh --push --pipeline house_price
```

**Environment variables for push:**

| Variable | Description | Example |
|----------|-------------|---------|
| `GCP_AR_HOST` | AR hostname | `us-east4-docker.pkg.dev` |
| `GCP_PROJECT_ID` | GCP project | `prj-my-sandbox` |
| `GCP_AR_REPO` | AR repository name | `mlplatform-second-run` |
| `IMAGE_TAG` | Tag override (default: `{branch}-{sha}`) | `v1.0.0` |

**Key behavior:**
- Tag is auto-derived from git (`{branch}-{short_sha}`) unless `IMAGE_TAG` is set
- `BASE_IMAGE` ARGs in Dockerfiles are auto-resolved via an internal registry
- Image names are resolved by calling `NamingConvention.docker_image_name()` from Python, ensuring bash and Python produce identical names
- Builds use `--platform linux/amd64` (Vertex AI runs on amd64)

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `FAILED_PRECONDITION` on AR push | Cloud Build SA lacks `artifactregistry.writer` | Grant `roles/artifactregistry.writer` to the CB SA |
| `403 Access Denied` on GCS | Cloud Build SA lacks `storage.objectAdmin` | Grant `roles/storage.objectAdmin` to the CB SA |
| `Permission denied` on `gcloud builds submit` | User lacks build permissions | Grant `roles/cloudbuild.builds.editor` to the user |
| `base-python: not found` in pipeline build | base-python not built yet | Run `scripts/docker_build_base.sh` first, or ensure Cloud Build steps 0-2 ran |
| `uv sync` fails with lock mismatch | `uv.lock` out of date | Run `uv lock` locally and commit the updated lockfile |
| Build succeeds but image is wrong arch | Missing `--platform` flag | Local script uses `--platform linux/amd64`; Cloud Build runs on amd64 natively |
| `_PIPELINE_DIR` vs `_PIPELINE` confusion | `_PIPELINE` is the slugified name (hyphens), `_PIPELINE_DIR` is the directory name (underscores) | Check both substitution values match your pipeline |
| Slow builds | No cache hit | Verify `:latest` tag exists in AR; first build of a new pipeline has no cache |
