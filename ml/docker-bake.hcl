# The CPU AI-matching workers, each built as one chain: its lean model image, then the worker
# layer (worker.Dockerfile) on top of exactly that build, through a named context. The worker's
# FROM never reads a registry or a local tag, so the image CI smoke-tests and pushes is the base
# it just built. Run from the repository root:
#
#   docker buildx bake -f ml/docker-bake.hcl kev-worker-cpu --load    # or pplx-worker-cpu
#
# CI (.github/workflows/ai-worker-image-build.yml) adds the OCI labels through
# docker/metadata-action, whose bake file merges into the `*-meta` targets below, and through
# --set clears the local tags, loads the image, pushes the same build by digest and sets the GHA
# cache; the registry tags go on only after the smoke test. No model weights go into any image:
# they are mounted from the host at run time.
# The GPU images stay local builds (docs/ai/worker.md, "Images").

group "default" {
  targets = ["kev-worker-cpu", "pplx-worker-cpu"]
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
    BASE = "base"
  }
}

target "kev-worker-cpu" {
  inherits = ["_worker", "kev-worker-cpu-meta"]
  contexts = {
    base = "target:kev-cpu-lean"
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
  labels = {
    "org.opencontainers.image.title"       = "makhzan pplx-worker-cpu"
    "org.opencontainers.image.description" = "makhzan AI-matching worker on pplx-decider-flash-v1.3, CPU only, no weights"
    "org.opencontainers.image.licenses"    = "Apache-2.0"
  }
}
