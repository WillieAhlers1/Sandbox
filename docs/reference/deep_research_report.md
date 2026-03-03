# A Python framework for local development and deployment to GCP with Cloud Composer DAGs and Vertex AI Pipelines

## Requirements and hard constraints that shape the design

Your requirements imply a **two-layer orchestration model**: orchestration and scheduling via **Cloud Composer** (managed Airflow), and model lifecycle (train/validate/deploy) inside **Vertex AI Pipelines**. Cloud Composer is a fully managed orchestration service built on entity["organization","Apache Airflow","workflow orchestrator"] and operated using Python. citeturn21search8turn10search5

A few platform realities directly influence how “framework-like” you can make this without fighting the substrate:

Cloud Composer stores DAGs in a Cloud Storage bucket and synchronises them from the bucket to Airflow components (workers/schedulers). citeturn22view0turn1search1turn21search4 This makes “deploying code” largely a matter of **syncing files into the environment’s `/dags` folder**, but it also means you must design for **DAG parsing constraints** (fast imports, minimal top-level work), because Airflow repeatedly executes DAG files when discovering them. citeturn16search0turn20search5turn20search10

Airflow naming constraints matter because you want metadata encoded into names/paths. Airflow’s `dag_id` must consist exclusively of alphanumeric characters plus dashes, dots, and underscores, and a `task_id` can only be added once per DAG (so your naming must guarantee uniqueness). citeturn15search0

Your stated governance principles—branch-based isolation, environment-agnostic portability, DRY, convention over configuration, and “code-as-a-model hygiene”—are well-aligned with industry guidance that DAGs should be treated as **production-level code with tests**, and with the availability of CI/CD patterns for Composer. citeturn15search2turn8view0turn5search7

Finally, two near-term GCP lifecycle events are relevant to “foundations” you build now:

- **Cloud Composer 1 and Composer 2.0.x end-of-life is 15 September 2026**, with guidance to plan migration. citeturn22view0turn17view0turn8view0  
- **Vertex AI Feature Store (Legacy) is deprecated**, with a change in support posture beginning 17 May 2026 and a full sunset on 17 February 2027; the advised direction is the newer Vertex AI Feature Store approach (BigQuery-backed). citeturn18view0turn1search3turn14view0

These dates mean your framework should assume Composer 2.1+ / Composer 3 patterns and **Vertex AI Feature Store (V2)** semantics, not Legacy.

## Existing frameworks and building blocks you can reuse

No single widely adopted open-source project exactly matches “Cloud Composer DAG framework + ingestion + transformation + feature tables + Vertex AI Pipelines training/deploy + uv + branch isolation + name-encoded metadata”. The most practical approach is to **reuse best-in-class building blocks** and build a thin “glue + conventions” layer.

### Orchestration and composable DAGs

Airflow already provides several primitives that can be treated as your “composition framework” if you codify conventions:

- **TaskFlow API**: define tasks as Python functions via `@task` and DAGs via `@dag`, reducing boilerplate and making refactors less invasive. citeturn2search1turn2search12  
- **Dynamic task mapping**: generate variable numbers of tasks at runtime based on upstream data, which supports “easy step changes” without rewriting static DAG code. citeturn2search6  
- **Runtime parameters**: Airflow “Params” support JSON Schema validation, providing a standard, environment-agnostic way to pass runtime configuration into DAG runs. citeturn15search11turn20search3  
- **Ignore rules for performance**: `.airflowignore` lets you exclude files/directories from parsing, which becomes important if you encode branch metadata into directory structures and have many DAG variants. citeturn16search5turn21search2turn16search17

Cloud Composer itself recommends separate production and test environments because Airflow does not provide strong DAG isolation. citeturn22view0 This dovetails with your branch-based isolation requirement: you can formalise “isolation levels” (local branch → shared dev → prod) rather than attempting full per-branch Composer environments by default.

### Data transformation layer

You have two strong, reuse-oriented options for the transformation step:

**Dataform (GCP-native)**: Dataform supports developing, testing, and version controlling SQL workflows that run in BigQuery. citeturn2search3turn2search7 Dataform runs can be scheduled/managed from Cloud Composer 2 using Dataform operators in Airflow DAGs. citeturn9search4turn9search1turn9search0 A key constraint is that “Dataform does not support Cloud Composer 1.” citeturn9search4

**dbt (portable)**: entity["organization","dbt","data build tool"] is positioned as a way to collaboratively transform data and deploy analytics code with software engineering practices (version control, modularity, portability, CI/CD, documentation). citeturn4search3 If you already have dbt usage across teams, reusing it can reduce “delta” substantially—but you will need to decide how to execute it from Composer (e.g., dbt Cloud operators exist for Airflow, while dbt Core typically requires you to run dbt in a containerised job environment). citeturn9search12turn9search16

### Feature store foundations

Given your “feature store foundation—entity-centric design” principle, the main reuse decision is whether you want **managed, BigQuery-backed feature serving** or an **open-source feature store abstraction**.

**Vertex AI Feature Store (V2, BigQuery-backed)**: Vertex AI Feature Store lets you manage feature data in BigQuery tables or views and serve features online from that BigQuery source; it acts as a metadata layer over BigQuery. citeturn14view0turn18view0 Its data model expects an ID column (entity identifier) and often a timestamp column for time-series feature data. citeturn14view0 Feature registration is optional (you can serve without registering), but has advantages such as latest-value serving when there are repeated entity IDs, and aggregating features across sources. citeturn14view0turn18view0

**Feast (open-source)**: entity["organization","Feast","open source feature store"] is an open-source feature store focused on defining/managing/serving features, including on GCP. citeturn0search7turn19search10turn19search13 Feast’s conceptual model is explicitly entity-centric: entities (and entity keys) should be reused across feature views to aid discovery and reuse. citeturn0search3turn0search11 Feast supports BigQuery as an offline store implementation and performs joins within BigQuery for training data retrieval. citeturn10search3turn10search7

The feature-store part of your framework can therefore be framed as: **standardise your entity model + feature definitions**, then choose whether the serving/registry layer is Vertex-managed or Feast-managed.

### Vertex AI Pipelines component for model lifecycle

Vertex AI Pipelines supports ML pipelines defined using either entity["organization","Kubeflow Pipelines","ml workflow platform"] / KFP or entity["organization","TensorFlow Extended","tfx pipeline framework"]. citeturn21search7turn21search3turn0search5 The Vertex guidance for building pipelines emphasises building with the KFP SDK so you can implement workflows by building custom components or reusing prebuilt components, including Google Cloud Pipeline Components (GCPC). citeturn0search1turn1search6turn1search12

For your requirement “train, validate and deploy”, two reused assets are especially relevant:

- **Google Cloud Pipeline Components** include components for training jobs, model evaluation, model upload, endpoint creation, and model deploy/undeploy operations. citeturn1search2turn1search6  
- **Pipeline templates** stored in Artifact Registry are designed for reuse and version control: a pipeline template is a reusable workflow definition, and the KFP RegistryClient can be used with Artifact Registry as a template registry. citeturn13view0turn12view0

This template mechanism matters to your “code-as-a-model hygiene”: you can compile pipelines in CI, store them centrally, and then have Composer-triggered runs reference a specific template version.

### How Composer triggers Vertex pipelines

Airflow’s Google provider includes operators for Vertex AI pipeline jobs—e.g., `RunPipelineJobOperator` to create and run a pipeline job. citeturn1search8 This provides a clean integration seam: a Composer DAG step can trigger a Vertex pipeline run after ingestion/transformation/feature steps complete.

### End-to-end templates you can cannibalise

Two existing sources are particularly reusable, but not turnkey:

- The public repo **GoogleCloudPlatform/mlops-with-vertex-ai** shows a CI/CD routine using Cloud Build that includes compiling a pipeline and uploading it (in that example, to Cloud Storage) and separate model-deployment routines. citeturn11view0turn5search1  
- Composer documentation includes a full “test, synchronise, deploy DAGs from GitHub” CI/CD guide with presubmit tests and DAG sync into the Composer bucket using Cloud Build. citeturn8view0turn22view0 It even describes a workflow that begins with changes pushed to a development branch and PRs to main, aligning well with your branch-based development model. citeturn8view0

These are not frameworks, but they contain the scaffolding and patterns you’d otherwise have to design from scratch.

## A reference architecture that meets your principles

image_group{"layout":"carousel","aspect_ratio":"16:9","query":["Cloud Composer Apache Airflow architecture diagram","Apache Airflow DAG graph view example","Vertex AI Pipelines Kubeflow pipeline diagram","Vertex AI Feature Store BigQuery feature view diagram"],"num_per_query":1}

A pragmatic “framework” for your scenario is best thought of as **a standard repository template + a Python library that enforces conventions + CI/CD automation**. The key is to reduce “edit surface area” for pipeline changes by pushing variability into *small, well-defined specifications* rather than editing large DAG files.

### Separation of concerns: thin DAGs, reusable components

A strong convention is: **DAGs orchestrate, services execute**. This aligns with Cloud Composer operational realities and parse-time constraints: minimise top-level logic and keep DAG files lightweight to avoid parse-time performance penalties. citeturn20search5turn20search10turn16search14

Concretely:

- Ingestion tasks should generally trigger managed jobs (e.g., Dataflow template jobs) rather than embedding heavy ingestion logic inside the DAG process. Airflow provides Dataflow operators such as `DataflowTemplatedJobStartOperator` and `DataflowStartFlexTemplateOperator`. citeturn10search0turn10search4  
- Transformation tasks should trigger Dataform workflow invocations (or dbt runs) rather than compiling SQL in the DAG. Dataform is explicitly intended to transform data after it has been loaded into BigQuery and can be invoked via Airflow operators. citeturn9search1turn9search4turn9search0  
- Feature-table tasks should materialise features into BigQuery tables/views and optionally register them in Vertex AI Feature Store, which expects feature data in BigQuery and provides a registry/metadata layer and online serving. citeturn14view0turn18view0  
- ML lifecycle tasks should trigger Vertex pipeline runs built from reusable components (GCPC and your own custom components), compiled and stored as templates. citeturn1search6turn13view0turn1search2  

This yields a consistent “macro flow”:

1) ingest → 2) transform → 3) build features → 4) run Vertex training/validation/deploy pipeline.

### Composition model: a pipeline spec + a step registry

To minimise edits when analysts/data scientists change steps, the most re-usable internal pattern is:

- A **PipelineSpec** (small Python object or declarative config) that expresses:
  - ordered steps (ingest/transform/features/train/etc)  
  - dependencies between steps  
  - parameter sets (source systems, target datasets, model parameters)  
- A **StepRegistry** mapping logical step types to concrete implementations:
  - “ingest-batch” → Dataflow template operator wrapper  
  - “transform” → Dataform invocation wrapper  
  - “features-materialise” → BigQuery SQL / Dataform action + registry call  
  - “train-and-deploy” → Vertex pipeline trigger wrapper

Airflow-native primitives help here:

- TaskFlow API allows you to write your wrapper steps as Python functions, decreasing boilerplate. citeturn2search1turn2search12  
- Dynamic task mapping lets you keep a single “ingest_step” code path that expands to N table ingestions depending on the spec, reducing code edits for adding/removing sources. citeturn2search6  
- Airflow Params can be used to supply runtime overrides (e.g., “run only to feature build”), with JSON Schema validation for hygiene. citeturn20search3turn15search11  

### Vertex pipeline template lifecycle integrated into the framework

To keep ML pipelines “composable, reusable, and branch-isolated”, the framework should standardise the lifecycle described in Vertex guidance: write pipeline code, compile it, then submit or reuse compiled definitions. citeturn21search11turn5search19

A production-friendly pattern is to pre-compile templates in CI and store them centrally:

- Vertex documentation defines pipeline templates as reusable workflow definitions and explicitly supports using Artifact Registry as the template registry with the KFP RegistryClient. citeturn13view0turn12view0  
- The template mechanism includes naming constraints: package names are derived from `pipeline_spec.pipeline_info.name` and must match `^[a-z0-9][a-z0-9-]{3,127}$` (4–128 chars, lowercase/digit and hyphens). citeturn13view0  
- Tags are supported, but are limited (up to eight tags) and are not required for a robust system. citeturn13view0  

This directly supports your “no tagging dependency” principle: encode the metadata you care about in the **package name** and/or **pipeline name**, and treat tags as optional ergonomics.

### Feature store integration as a first-class framework module

If you select Vertex AI Feature Store (V2), your framework’s feature module can standardise:

- how feature data is shaped in BigQuery (columns = features; rows keyed by entity ID; timestamps for time-series) citeturn14view0  
- how features are registered: creation of feature groups and features is optional but recommended when needed (e.g., repeated entity IDs, aggregation across sources). citeturn14view0  
- location constraints: Feature Store resources must be in the same region or multi-region as the BigQuery data source. citeturn14view0  

If you select Feast, your framework standardises:

- entity definitions and reuse across feature views (your “entity-centric foundation”) citeturn0search3  
- offline store selection (e.g., BigQuery offline store, joins in BigQuery) citeturn10search3turn10search7  

Either way, your framework does the enforcing (naming, schema conventions, CI checks), while the feature store provides serving/registry mechanics.

## Naming, branch isolation, and environment-agnostic execution

Your “metadata in path/name” standard is feasible, but you must account for **different naming constraints across services**. A robust approach is to define a **canonical namespace** and a set of **service-specific normalisations**.

### Canonical namespace and Airflow IDs

A canonical identifier like:

`<team>-<project>-<branch>`

works well for many parts of Airflow naming because `dag_id` supports dashes, dots, and underscores. citeturn15search0 This is compatible with your requirement to avoid tagging: the metadata is in the ID itself.

However, you should enforce:

- length limits (practical, even if not always enforced at parse time) because operational subsystems like metrics exporters can break with long names (e.g., known issues when `dag_id/task_id` combinations are too long for certain metric name limits). citeturn15search19  
- uniqueness: `task_id` uniqueness within a DAG is strict, so step factories must generate deterministic, collision-free task IDs. citeturn15search0  

### BigQuery naming constraints force a normalisation strategy

BigQuery dataset names cannot contain spaces or special characters such as hyphen (`-`); underscores are allowed. citeturn6search1

So if your canonical namespace is `team-project-branch`, your BigQuery dataset namespace likely must be mapped to:

`team_project_branch`

This is not “tagging”; it is applying a consistent transformation while retaining the metadata in the name.

### Vertex pipeline template names support your naming principle

Vertex pipeline templates in Artifact Registry have explicit package naming constraints that are compatible with kebab-case metadata encoding (lowercase + hyphens, 4–128 chars). citeturn13view0 This makes them a good target for your required `[team]-[project]-[branch]` encoding.

For branch isolation, you can make template package names branch-scoped (e.g., `team-project-branch-train`), and use CI to publish a new version per commit.

### Branch-based isolation: recommended “levels” rather than per-branch Composer environments

Cloud Composer explicitly notes that Airflow does not provide strong DAG isolation and recommends separate production and test environments to prevent interference. citeturn22view0 A scalable interpretation for your framework is:

- **Local developer isolation**: each developer branch runs locally with its own namespace.
- **Shared dev isolation**: a dev Composer environment that receives merged changes and runs pipelines against dev datasets/schemas.
- **Production isolation**: a prod Composer environment that runs only released DAGs and targets production datasets/schemas.

The Composer CI/CD guide already aligns with this model: changes pushed to a development branch, PR to main, Cloud Build runs DAG unit tests, then deploys to a development environment; only after validation are DAGs promoted to production. citeturn8view0

To preserve branch metadata without deploying a large number of branch DAG files into Composer (which increases parse load), combine:

- Strong naming conventions for outputs (datasets/tables/models) that incorporate branch in dev.
- `.airflowignore` rules to prevent non-release artefacts from being parsed. citeturn16search5turn21search2  
- Avoiding “paused DAG accumulation”: Cloud Composer notes paused DAGs are still parsed; improving performance requires using `.airflowignore` or removing unused DAG files. citeturn21search2turn16search17  

### Environment-agnostic configuration injection

To keep code environment-agnostic, the framework should standardise “how config is supplied” rather than hardcoding project IDs/datasets in code:

- Airflow Connections can be defined via environment variables or external secrets backends (or the metadata DB), enabling decoupling from code. citeturn6search3  
- Airflow Params provide runtime configuration validated with JSON Schema, supporting “change steps without heavy edits” by passing structured overrides. citeturn20search3turn15search11  
- For Composer specifically, remember DAG code is “deployed by syncing files to the bucket”; the sync is unidirectional (bucket → Airflow components), so local mutations on workers are overwritten. citeturn21search4turn22view0  

## Developer workflow, uv usage, and hygiene-by-design

### uv as the foundation for reproducible local development

Your requirement to use “UV” maps well to the tooling offered by entity["company","Astral","python tooling company"]’s uv:

- uv supports Python projects defined in `pyproject.toml`. citeturn0search2turn0search6  
- `uv.lock` is a cross-platform lockfile containing exact resolved versions; it should be checked into version control for consistent installs across machines. citeturn7search1turn7search11turn20search4  
- uv describes locking and syncing as distinct processes and supports automatic “lock and sync” behaviours to keep environments up to date. citeturn7search0turn20search12  

In practice, this means your framework template can enforce:
- a single `pyproject.toml` source of truth (broad requirements)  
- one committed `uv.lock` (exact set)  
- standard commands (`uv sync`, `uv run`) for both analysts and data scientists.

### Bridging uv to Cloud Composer dependency management

Cloud Composer installs Python dependencies as environment packages, and dependency conflicts are a common failure mode during environment updates when custom PyPI packages conflict with preinstalled packages. citeturn17view0turn2search17

To align uv with Composer reality, the framework should standardise a “publishable dependency artefact” flow:

- Use uv for development lockfiles, then export/emit a pinned dependency set for CI/CD or Composer environment configuration. uv supports exporting lock information to other formats for integration workflows. citeturn7search13turn6search0  
- Keep Composer’s global environment dependency footprint small; isolate conflicting libraries using operators designed for dependency isolation (Composer troubleshooting explicitly mentions isolating snippets via PythonVirtualenvOperator as one mitigation). citeturn17view0  

### CI/CD hygiene for DAGs and templates

Cloud Composer provides an explicit CI/CD approach using Cloud Build that:
- runs unit tests for DAG validity on pull requests,
- synchronises DAGs to a dev Composer environment after merge,
- and then promotes to production after validation. citeturn8view0

This aligns with Airflow guidance to treat DAGs as production-grade code with associated tests. citeturn15search2

Additionally, the Composer CI/CD guide notes that dependency sets in Cloud Build’s test container may differ from what is installed in Composer and recommends running a local Airflow environment during DAG development. citeturn8view0 This supports your goal of local development parity.

For Vertex pipelines, a parallel “template CI/CD” is supported by Vertex guidance and examples:
- write pipeline code → compile pipeline templates → store centrally → trigger runs. citeturn21search11turn13view0turn12view0  
- sample patterns in Google’s “mlops-with-vertex-ai” show Cloud Build routines that compile and upload pipeline definitions. citeturn11view0turn5search1

## Delta analysis: what you can reuse and what you still need to build

This section focuses on “what’s the delta” in terms of the *additional engineering* required to meet your specific constraints (uv, naming-with-metadata, branch isolation, feature store entity-centric foundation, and flexible composition).

### Reuse-heavy option: Composer + Dataform + Vertex Feature Store (V2) + Vertex pipeline templates

**What you largely get “for free”**
- Orchestration substrate, deployment mechanics, and CI/CD patterns for DAGs from Composer docs. citeturn22view0turn8view0  
- SQL transformation lifecycle geared for analysts via Dataform (develop/test/version control), and first-class Airflow operators for invoking Dataform workflows in Composer 2. citeturn2search3turn9search4turn9search1  
- Feature management and online serving patterns directly tied to BigQuery tables/views, with an explicit ID-based (entity-like) data model and optional registry for reuse/discovery. citeturn14view0turn18view0  
- A reusable, versioned mechanism for ML training/validation/deploy pipelines via pipeline templates in Artifact Registry, with clear naming constraints that support metadata-in-name. citeturn13view0turn12view0  
- A direct trigger integration from Airflow to Vertex pipeline runs via `RunPipelineJobOperator`. citeturn1search8  

**The delta you still need to implement**
- A Python “framework library” that:
  - defines PipelineSpec/StepRegistry conventions (so users edit *spec*, not DAG internals),
  - generates DAGs systematically with enforced naming,
  - provides standard component wrappers (Dataflow/Dataform/Feature Store/Vertex pipeline trigger).
- A naming/normalisation module that consistently maps canonical IDs to Airflow IDs, BigQuery datasets (hyphen → underscore), and Vertex template package names (lowercase + hyphens within regex). citeturn6search1turn15search0turn13view0  
- A uv-based repo template plus “export to Composer-compatible dependency artefacts”, acknowledging Composer dependency conflict risks. citeturn7search1turn17view0turn7search13  
- Branch isolation policy implementation (what is isolated by name vs by environment), consistent with Composer’s weak DAG isolation note and parse-time constraints. citeturn22view0turn21search2turn16search5  

**Indicative effort (engineering estimate, not a guarantee)**
- If you already run Composer and Vertex Pipelines and are standardising rather than inventing, this is typically a **medium build**: roughly **6–12 person-weeks** to deliver a first usable internal framework that supports 1–2 “golden path” pipelines end-to-end, plus additional time per new data source type/operator wrapper (commonly 1–3 days each).

Where effort tends to concentrate is not the DAG code itself, but:
- getting naming and isolation right across services (and enforcing it),
- a clean developer experience (local tests, CI gating),
- and handling dependency parity/conflicts in Composer environments. citeturn17view0turn8view0turn6search1  

### Portable option: Composer + dbt + Feast + Vertex pipelines

**Why reuse is attractive**
- dbt is explicitly aligned with software engineering practices and portability for analytics transformations. citeturn4search3  
- Feast is explicitly designed for feature reuse and entity-centric modelling, and has GCP support. citeturn0search7turn0search3turn19search13  

**Delta relative to the reuse-heavy option**
- You must implement/run a stable execution environment for dbt and Feast (and make it easy for analysts to use). Airflow can trigger dbt Cloud jobs via provider operators, but dbt Core execution typically needs container/job infrastructure. citeturn9search12turn9search16  
- You must decide how Feast’s online store maps to your runtime serving needs; Feast supports GCP online store defaults (e.g., Datastore) but your org may prefer different online serving patterns. citeturn19search13  
- You still need the same “framework glue” (PipelineSpec, naming library, CI/CD, uv integration), but also need to manage more OSS runtime surface area.

**Indicative effort**
- Typically **10–20 person-weeks** for a first robust platform slice, because you are building (or formalising) more execution infrastructure and operational practices around dbt and Feast, in addition to the DAG and pipeline template layer.

### DS/analyst editing minimisation option: embed an internal pipeline framework (Kedro-style) under Airflow

If your biggest pain is “lots of edits when steps change”, you can adopt a project-level pipeline abstraction such as entity["organization","Kedro","python data pipeline framework"], which supports modular pipelines and the ability to instantiate modular pipelines as reusable templates with different inputs/outputs/parameters. citeturn3search4turn3search0turn3search12

There is also ecosystem support for exporting/deploying Kedro pipelines into Airflow (e.g., Kedro-Airflow is described as allowing deployment of Kedro pipelines as Airflow DAGs). citeturn19search8turn19search14

**Delta**
- You still must build your organisation’s naming/isolation/enforcement layer (Kedro won’t impose your `[team]-[project]-[branch]` encoding automatically).
- You must align Kedro’s execution model with Composer operational constraints (DAG parsing time, dependency management).
- You must still build Vertex pipeline template integration (Kedro won’t replace Vertex AI pipeline definitions for training/validation/deploy).

**Indicative effort**
- Commonly **12–22 person-weeks**, because you are effectively standardising two abstractions (Kedro project pipelines + Airflow orchestration + Vertex pipeline lifecycle) and need disciplined guardrails to stop the system becoming harder to operate than plain Airflow.

### Alternative orchestrators (not aligned with the Cloud Composer non-negotiable)

Tools like entity["organization","Dagster","data orchestration platform"], entity["organization","Prefect","python workflow orchestration"], entity["organization","Flyte","workflow orchestrator on kubernetes"], and entity["organization","Metaflow","data science workflow framework"] provide rich composition abstractions (assets/flows/workflows) and strong local-development stories. citeturn3search2turn3search11turn4search17turn3search17turn19search12 entity["company","Netflix","streaming company"] is relevant historically because Metaflow originated there. citeturn3search17turn19search12

However, adopting them as the *primary* orchestrator would violate your constraint of “DAGs through Cloud Composer”, unless you renegotiate that constraint or use them only inside tasks. Even “bridge” integrations (e.g., Dagster monitoring/migration tooling for Airflow) are oriented toward transition rather than unified operation on Composer. citeturn19search0turn19search4

### A concrete way to think about “refactoring effort” for adoption

The most reliable predictor of refactoring effort is not which stack you choose, but **what you already have**:

If you already have many hand-written DAGs, the refactor is largely:
- extracting common patterns into TaskFlow/TaskGroup abstractions and a step registry,
- replacing per-DAG hardcoded names and paths with the naming library,
- and adding CI tests and dependency discipline to stop regressions. citeturn2search1turn15search2turn8view0turn17view0

If you have primarily notebooks/scripts, the refactor is larger:
- turning scripts into repeatable ingestion/transform/feature components,
- moving ML steps into compiled Vertex pipelines (KFP/TFX),
- and implementing template publishing (Artifact Registry) so Composer only triggers versioned templates. citeturn21search7turn13view0turn1search6turn1search8

As a rule of thumb:
- **Standardising existing Airflow + BigQuery usage** often looks like “moderate refactor” (weeks).
- **Operationalising notebooks into end-to-end, versioned pipelines** often looks like “substantial refactor” (months), because you are establishing CI/CD and artefact/versioning discipline across data + features + models. citeturn5search7turn13view0turn15search2