# Docker Image Strategy — Design Discussion

## 1. Problem Statement

The framework needs to support multiple Docker images per pipeline. The original design
assumed one image per pipeline (the "training" image), but real-world ML workflows
require different containers for different purposes:

| Use Case | Image Characteristics |
|---|---|
| **Training (batch)** | Heavy deps (sklearn, xgboost, torch), data access libs, full framework |
| **Online serving** | Lightweight, HTTP server (FastAPI/Flask), model loading, prediction only |
| **Preprocessing** | Data transformation libs, Spark/Beam connectors |
| **GPU inference** | CUDA runtime, model-specific serving framework |

When registering a model in Vertex AI Model Registry, the `serving_container_image_uri`
determines what container runs when the model is deployed to an endpoint. If this
defaults to the training image, online serving deployments carry unnecessary
dependencies, increasing cold start time, attack surface, and cost.

Additionally, GCP explicitly separates training and serving containers:
- `aiplatform.Model.upload()` takes `serving_container_image_uri` as a distinct parameter
- Custom serving containers must implement HTTP health/prediction endpoints
- Custom Prediction Routines (CPR) provide Google-managed base images optimized for serving
- Pre-built containers exist for standard frameworks (sklearn, TensorFlow, PyTorch)

---

## 2. Current State (Before This Change)

### Directory Structure

```
docker/
    base/
        base-python/
            Dockerfile          # Python 3.12 + uv foundation
    pipeline/
        Dockerfile              # Single training image for all pipelines
```

### How It Works

1. `docker_build.sh` builds `base-python`, then one image per pipeline directory using
   `docker/pipeline/Dockerfile`
2. Image naming: `{ar_host}/{gcp_project}/{team}-{project}/{pipeline-slug}:{branch}-{sha}`
3. The compiler injects this single image as both:
   - `base_image` for all KFP container components (training steps)
   - `serving_container_image` for RegisterModel (when user doesn't set one)
4. No way to specify a different serving image without hardcoding a full URI

### Limitations

- **One image per pipeline** — all steps in a pipeline share the same container
- **Training image == serving image** — wasteful for online deployment
- **No convention for serving Dockerfiles** — users must hardcode full AR URIs
- **Naming logic duplicated** — bash script and Python framework each implement their own

---

## 3. Approaches Considered

### Approach A: Directory-Based Hierarchy

Separate `docker/` subdirectories for each image type:

```
docker/
    base/base-python/Dockerfile
    pipelines/default/Dockerfile
    pipelines/house_price/Dockerfile
    serving/default/Dockerfile
    serving/house_price/Dockerfile
```

**Pros:**
- Clean separation of concerns; each Dockerfile gets its own build context
- Default/override pattern is familiar

**Cons:**
- Serving logic is far from the pipeline it belongs to. A data scientist working on
  `house_price` must look in two separate directories.
- For N pipelines with custom serving images: 2N directories to manage
- Harder to see at a glance what images a pipeline uses
- The "default vs override" resolution adds implicit framework magic

### Approach B: Co-Located Named Dockerfiles (Chosen)

All Dockerfiles for a pipeline live together under `docker/pipelines/{name}/`:

```
docker/
    base/base-python/Dockerfile
    train.Dockerfile                    # Default training image
    serve.Dockerfile                    # Default serving image
    pipelines/
        house_price/
            house_price_base.Dockerfile # Custom training (FROM default or base-python)
            house_price_app.Dockerfile  # Custom serving  (FROM default or base-python)
```

**Pros:**
- Everything for a pipeline is co-located — data scientist sees all images in one place
- Scales naturally — add any number of `*.Dockerfile` files
- No default/override complexity — inheritance is handled by Docker's own `FROM`
- Build script just globs `*.Dockerfile` — simple and predictable
- Component-level image binding (`image_name="house_price_app"`) maps directly to files
- Unrestricted naming — no hardcoded "train"/"serve" convention

**Cons:**
- Slight duplication if many pipelines share identical Dockerfiles (mitigated by `FROM`
  shared base images)
- Pipelines directory is not pure Python anymore... **but wait** — we keep `pipelines/`
  as pure Python modules and put Dockerfiles under `docker/pipelines/`. This preserves
  the separation.

---

## 4. Chosen Design: Approach B with Defaults

### 4.1 Directory Structure

```
docker/
    base/
        base-python/
            Dockerfile                      # Layer 0: Python foundation (→ separate repo later)
    train.Dockerfile                        # Default training image (Layer 1)
    serve.Dockerfile                        # Default serving image (Layer 1)
    pipelines/
        house_price/
            house_price_base.Dockerfile     # Pipeline-specific (FROM train or base-python)
            house_price_app.Dockerfile      # Pipeline-specific (FROM serve or base-python)
        churn/
            churn_train.Dockerfile
            churn_serve.Dockerfile
            churn_gpu_inference.Dockerfile  # Arbitrary names are fine

pipelines/                                  # Pure Python — NO Dockerfiles here
    house_price/
        pipeline.py
        steps/
        sql/
```

### 4.2 Dockerfile Inheritance — Stem-Based Resolution

Data scientists reference base images by **stem name only** (the Dockerfile's filename
without `.Dockerfile`). They never need to know the resolved image URI.

The build script maintains an **image registry** — an in-memory map of
`stem → full_tag` — populated as each image is built. When a Dockerfile declares
`ARG BASE_IMAGE=<stem>`, the build script looks up the stem in the registry and
passes the resolved full tag as `--build-arg BASE_IMAGE=<full_tag>`.

**Resolution order for `ARG BASE_IMAGE=<value>`:**

1. Look up `<value>` in the image registry (images built earlier in the same run)
2. If not found, use `<value>` as-is (external image, e.g., a Google CPR base image)

**Examples:**

```dockerfile
# docker/pipelines/house_price/house_price_train.Dockerfile
# "train" is the stem of docker/train.Dockerfile — resolved automatically.
ARG BASE_IMAGE=train
FROM ${BASE_IMAGE}
RUN pip install xgboost-gpu
```

```dockerfile
# docker/pipelines/house_price/house_price_app.Dockerfile
# Inherits from the pipeline's own training image by stem name.
ARG BASE_IMAGE=house_price_train
FROM ${BASE_IMAGE}
# Add serving-specific deps...
```

```dockerfile
# docker/pipelines/churn/churn_serve.Dockerfile
# External base image — not in registry, used as-is.
FROM us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-3:latest
COPY pipelines/churn/serve/ /app/
```

**Registry state during a build run:**

| After building... | Registry gains |
|---|---|
| `docker/base/base-python/Dockerfile` | `base-python` → `{ar}/base-python:main-abc` |
| `docker/train.Dockerfile` | `train` → `{ar}/train:main-abc` |
| `docker/serve.Dockerfile` | `serve` → `{ar}/serve:main-abc` |
| `docker/pipelines/house_price/house_price_train.Dockerfile` | `house_price_train` → `{ar}/house-price--house-price-train:main-abc` |
| `docker/pipelines/house_price/house_price_app.Dockerfile` | `house_price_app` → `{ar}/house-price--house-price-app:main-abc` |

This means `house_price_app.Dockerfile` can write `ARG BASE_IMAGE=house_price_train`
and it resolves to the full AR URI — no manual URI construction needed.

### 4.3 Component-Level Image Binding

Components reference images by the Dockerfile stem (filename without `.Dockerfile`):

```python
pipeline = (
    Pipeline(name="house_price", schedule="@daily")
    # Training step — uses "house_price_base" image
    .add(HouseTrainModelStep(image_name="house_price_base"))
    # Register — uses "house_price_app" as serving container
    .add(RegisterModel(image_name="house_price_app"))
    .build()
)
```

**Resolution priority** for `serving_container_image` in RegisterModel:

| Priority | Field | Behavior |
|---|---|---|
| 1 | `serving_container_image` (full URI) | Use as-is — escape hatch for external images |
| 2 | `image_name` (Dockerfile stem) | Resolve via `NamingConvention.image_uri()` |
| 3 | Neither set | Fall back to pipeline's default training image |

### 4.4 Image Naming Convention

Image names are derived from the Dockerfile location and stem to prevent collisions:

| Dockerfile Location | Image Name | Full Example |
|---|---|---|
| `docker/train.Dockerfile` | `train` | `{repo}/train:main-abc1234` |
| `docker/serve.Dockerfile` | `serve` | `{repo}/serve:main-abc1234` |
| `docker/pipelines/house_price/house_price_base.Dockerfile` | `house-price--house-price-base` | `{repo}/house-price--house-price-base:main-abc1234` |
| `docker/pipelines/churn/churn_serve.Dockerfile` | `churn--churn-serve` | `{repo}/churn--churn-serve:main-abc1234` |

Where `{repo}` = `{ar_host}/{gcp_project}/{team}-{project}`

The `--` (double-dash) delimiter separates the pipeline scope from the image purpose,
avoiding ambiguity with single dashes in names.

### 4.5 Race Condition Prevention

Multiple projects and branches can build concurrently. The naming convention ensures
zero collisions at every level:

| Collision Risk | Isolation Mechanism |
|---|---|
| **Project A vs Project B** | Separate AR repositories: `{team}-{projectA}` vs `{team}-{projectB}` |
| **`main` vs `feature-x`** (same project) | Tag: `main-abc1234` vs `feature-x-def4567` |
| **`house_price` vs `churn`** (same branch) | Image name prefix: `house-price--*` vs `churn--*` |
| **Two Dockerfiles in same pipeline** | Different stems: `house-price--base` vs `house-price--app` |
| **Root default vs pipeline-specific** | No prefix for root (`train`), prefixed for pipeline (`house-price--train`) |

### 4.6 GCP / Vertex AI Alignment

| GCP Best Practice | Framework Support |
|---|---|
| Separate training & serving containers | `train.Dockerfile` + `serve.Dockerfile` convention |
| CPR base images for serving | Pipeline `serve.Dockerfile` can `FROM` Google's CPR base |
| Pre-built containers (sklearn, TF, etc.) | `serving_container_image` full URI escape hatch |
| Custom HTTP serving containers | Any `*.Dockerfile` with the right CMD/EXPOSE |
| Model artifacts in GCS | `TrainModel` uploads to GCS; serving container loads from there |
| Container isolation (security) | Training and serving images have separate, minimal dependency sets |

---

## 5. Consolidated Image Name Resolution

**Single source of truth:** `gcp_ml_framework/naming.py` — the `NamingConvention` class.

Both the Python framework (compiler, components) and the bash build script resolve
image names through the same logic. The build script calls a Python helper
(`scripts/resolve_image.py`) to ensure consistency.

### Resolution Function (in `NamingConvention`)

```python
def docker_image_name(
    pipeline_name: str | None,
    dockerfile_stem: str,
) -> str:
    """
    Derive the AR image name from a Dockerfile's location.

    Args:
        pipeline_name: The pipeline directory name, or None for root-level Dockerfiles.
        dockerfile_stem: The filename without '.Dockerfile' (e.g., 'train', 'house_price_app').

    Returns:
        Slugified image name with pipeline prefix when applicable.

    Examples:
        docker_image_name(None, "train")                → "train"
        docker_image_name("house_price", "house_price_base") → "house-price--house-price-base"
    """
```

### Full URI Resolution

```python
# NamingConvention.image_uri() composes the full AR path:
# {ar_host}/{gcp_project}/{team}-{project}/{image_name}:{branch}-{sha}
```

### Build Script Integration

```bash
# docker_build.sh calls Python for name resolution:
image_name=$(uv run python -m scripts.resolve_image "$pipeline_name" "$stem")
```

This eliminates the duplicated slugify/naming logic that previously existed
independently in bash and Python.

---

## 6. Build Script Behavior

### Build Order (dependency-safe)

The build order ensures every `ARG BASE_IMAGE=<stem>` reference is resolvable:

```
Layer 0: docker/base/base-python/Dockerfile         → base-python:{tag}
Layer 1: docker/train.Dockerfile                     → train:{tag}           (can reference: base-python)
         docker/serve.Dockerfile                     → serve:{tag}           (can reference: base-python)
Layer 2: docker/pipelines/{name}/*.Dockerfile        → {name}--{stem}:{tag}  (can reference: any Layer 0/1 + siblings)
```

### Image Registry

The build script maintains a bash associative array (`IMAGE_REGISTRY`) mapping
stem → full tag. After each successful build, the image is registered:

```bash
declare -A IMAGE_REGISTRY
# After building base-python:
IMAGE_REGISTRY["base-python"]="us-east4-docker.pkg.dev/.../base-python:main-abc"
# After building train.Dockerfile:
IMAGE_REGISTRY["train"]="us-east4-docker.pkg.dev/.../train:main-abc"
```

When processing a Dockerfile, the script:
1. Extracts `ARG BASE_IMAGE=<stem>` from the file
2. Looks up `<stem>` in `IMAGE_REGISTRY`
3. Passes the resolved full tag as `--build-arg BASE_IMAGE=<full_tag>`
4. If `<stem>` is not in the registry, uses it as-is (external image)

### Discovery

The build script auto-discovers Dockerfiles:
- Root-level: `docker/*.Dockerfile`
- Pipeline-specific: `docker/pipelines/*/*.Dockerfile`

No configuration file needed. Add a Dockerfile → it gets built.

### Selective Builds

```bash
# Build everything
./scripts/docker_build.sh --push

# Build only a specific pipeline's images (still builds Layer 0+1 as dependencies)
./scripts/docker_build.sh --push --pipeline house_price
```
