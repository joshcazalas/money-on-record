# Engineering toolchain

## Python and uv

Python 3.14 is the current project and AWS Lambda baseline. `.python-version`, `pyproject.toml`,
and the committed universal `uv.lock` are the sources of truth. uv creates and
maintains `.venv` automatically; contributors should use `uv run` and should not
activate or hand-edit that environment.

Development dependencies use the standardized `dev` dependency group rather
than a published package extra:

- Ruff formats and lints.
- ty type-checks. ty is usable and fast, but still evolves rapidly, so its exact
  version is locked and CI invokes `ty check` directly.
- pytest remains the test runner. uv has no replacement for pytest; uv provides
  the environment and command execution around it.
- `uv audit --locked` checks the resolved dependency graph. The audit command is
  an explicitly enabled uv preview feature.

The audit currently blocks every known vulnerability or adverse project status.
That is intentionally stricter than the desired minimum of fixable HIGH and
CRITICAL vulnerabilities. uv does not currently expose severity and
ignore-unfixed policy flags, so implementing that exact threshold would require
maintaining a policy adapter around its JSON output. Add that only if
non-actionable lower-severity findings become noisy; do not hide actionable
findings to make CI green.

The repository enables uv's CycloneDX SBOM export preview for the future release
pipeline, but release SBOM generation is not yet a CI gate.

## Nix and direnv

`flake.nix` provides uv, Python 3.14, AWS CLI v2, Git, jq, actionlint,
ShellCheck, Syft, Terraform, and TFLint. `flake.lock` pins nixpkgs. The shell prevents uv
from downloading a second Python by exporting the Nix Python interpreter and
disabling managed Python downloads.

Trivy is deliberately absent from the development environment and CI. The
project will not add it indirectly through an action, container, or installer.
If an IaC scanner is selected later, it must receive a separate supply-chain
review and an immutable version/digest pin before adoption.

`.envrc` calls `use flake`. On first checkout:

```bash
direnv allow
```

Developers who do not use Nix need only uv for the current Python work. The
Terraform and supply-chain tools become required when those parts of the repo
exist.

## Repository automation

Reusable application-aware Python code belongs in the main package at first so
it receives the same tests and type checking. `tools/` is reserved for genuine
repository-wide automation. It is not a separate uv workspace today: a
workspace becomes worthwhile only when there are multiple independently
packaged Python projects that should share one lockfile.

The main CI workflow fans independent checks into separate jobs so warm-cache
PR checks can target the one-to-two-minute range:

- Ruff formatting and linting
- ty
- pytest
- offline versioned-data validation and generated-dictionary drift
- uv dependency audit
- source and wheel builds

GitHub Action references are pinned to full commit SHAs. The Nix environment
provides actionlint for local workflow validation.

## Versioned data contract

`mor-l0 validate-versioned` performs an offline, fail-closed validation of the
safe artifacts that are allowed in Git:

- inventory, manifest, dataset, artifact-path, byte-count, and SHA-256
  consistency;
- content integrity and dataset identity for committed metadata;
- profile-to-acquisition-manifest provenance and row-floor consistency;
- a required redacted fixture for every source; and
- the public-field allowlist and PII scan for every fixture.

CI also regenerates field dictionaries from committed metadata and rejects a
diff. Raw City data remains ignored and is not required by PR checks.
