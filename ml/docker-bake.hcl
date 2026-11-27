# The AI-matching worker images. worker-llamacpp, production since 2026-11-27, is the worker alone
# on python-slim (ml/worker-llamacpp.Dockerfile). The torch CPU workers, kept for a rollback, are
# each built as one chain: its lean model image, then the worker layer (worker.Dockerfile) on top
# of exactly that build, through a named context. The worker's
# FROM never reads a registry or a local tag, so the image CI smoke-tests and pushes is the base
# it just built. Run from the repository root:
#
#   docker buildx bake -f ml/docker-bake.hcl worker-llamacpp --load   # or kev-/pplx-worker-cpu
#
# CI (.github/workflows/ai-worker-image-build.yml) adds the OCI labels through
# docker/metadata-action, whose bake file merges into the `*-meta` targets below, and through
# --set clears the local tags, loads the image, pushes the same build by digest and sets the GHA
# cache; the registry tags go on only after the smoke test. No model weights go into any image:
# they are mounted from the host at run time.
# The GPU images stay local builds (docs/ai/worker.md, "Images").

# The commit the worker layer records (MAKHZAN_IMAGE_REVISION, reported at hello). CI sets it
# to the commit it builds (REVISION=$GITHUB_SHA in the bake's environment); "local" otherwise.
variable "REVISION" {
  default = "local"
}

group "default" {
  targets = ["worker-llamacpp", "kev-worker-cpu", "pplx-worker-cpu"]
}

target "_amd64" {
  platforms = ["linux/amd64"]
}

# --- the lean model images ----------------------------------------------------------------

target "kev-cpu-lean" {
  inherits   = ["_amd64"]
  context    = "ml/kev"
  dockerfile = "Dockerfile.cpu-lean"
}

target "pplx-cpu-lean" {
  inherits   = ["_amd64"]
  context    = "ml/pplx"
  dockerfile = "Dockerfile.cpu-lean"
}

# --- the workers --------------------------------------------------------------------------

# Local tags (CI clears them); in CI docker/metadata-action's bake file (bake-target =
# "<image>-meta") adds the source, revision and created labels.
target "worker-llamacpp-meta" {
  tags = ["makhzan-ml/worker-llamacpp:local"]
}

target "kev-worker-cpu-meta" {
  tags = ["makhzan-ml/kev-worker-cpu:local"]
}

target "pplx-worker-cpu-meta" {
  tags = ["makhzan-ml/pplx-worker-cpu:local"]
}

target "_worker" {
  inherits   = ["_amd64"]
  context    = "ml"
  dockerfile = "worker.Dockerfile"
  # FROM ${BASE}: "base" resolves to the named context each worker sets, never a registry.
  args = {
    BASE     = "base"
    REVISION = REVISION
  }
}

target "kev-worker-cpu" {
  inherits = ["_worker", "kev-worker-cpu-meta"]
  contexts = {
    base = "target:kev-cpu-lean"
  }
  # The repository the image names itself by at hello; CI sets the GHCR one (--set).
  args = {
    IMAGE_REPO = "makhzan-ml/kev-worker-cpu"
  }
  labels = {
    "org.opencontainers.image.title"       = "makhzan kev-worker-cpu"
    "org.opencontainers.image.description" = "makhzan AI-matching worker on Kev-4B (jaredpalmer/kev), CPU only, no weights"
    "org.opencontainers.image.licenses"    = "Apache-2.0"
  }
}

target "pplx-worker-cpu" {
  inherits = ["_worker", "pplx-worker-cpu-meta"]
  contexts = {
    base = "target:pplx-cpu-lean"
  }
  args = {
    IMAGE_REPO = "makhzan-ml/pplx-worker-cpu"
  }
  labels = {
    "org.opencontainers.image.title"       = "makhzan pplx-worker-cpu"
    "org.opencontainers.image.description" = "makhzan AI-matching worker on pplx-decider-flash-v1.3, CPU only, no weights"
    "org.opencontainers.image.licenses"    = "Apache-2.0"
  }
}

# The production worker since 2026-11-27: the llama.cpp backend, no torch and no model code
# (ml/worker-llamacpp.Dockerfile), on the pinned python-slim base; no lean model image under it.
# The torch workers above stay built and published, for a rollback.
target "worker-llamacpp" {
  inherits   = ["_amd64", "worker-llamacpp-meta"]
  context    = "ml"
  dockerfile = "worker-llamacpp.Dockerfile"
  args = {
    IMAGE_REPO = "makhzan-ml/worker-llamacpp"
    REVISION   = REVISION
  }
  labels = {
    "org.opencontainers.image.title"       = "makhzan worker-llamacpp"
    "org.opencontainers.image.description" = "makhzan AI-matching worker for a llama.cpp sidecar (Kev-4B Q4_K_M, pplx-decider Q4_K_S), no torch, no weights"
    "org.opencontainers.image.licenses"    = "Apache-2.0"
  }
}
