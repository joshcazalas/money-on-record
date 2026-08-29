#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
  echo "usage: $0 SOURCE_DIRECTORY ENVIRONMENT STATE_EXISTS RESULT_PARENT_DIRECTORY" >&2
  exit 64
fi

source_directory="$(realpath "$1")"
environment="$2"
state_exists="$3"
result_parent_directory="$(realpath -m "$4")"
script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
terraform_root="infra/components/static-site"

case "$environment" in
  production|uat)
    ;;
  *)
    echo "Unrecognized Terraform environment: $environment" >&2
    exit 64
    ;;
esac

if [[ "$state_exists" != "true" && "$state_exists" != "false" ]]; then
  echo "STATE_EXISTS must be true or false." >&2
  exit 64
fi

result_directory="$result_parent_directory/$environment"
root_directory="$(realpath -m "$source_directory/$terraform_root")"
case "$root_directory" in
  "$source_directory"/*)
    ;;
  *)
    echo "Terraform root resolves outside the checked-out source." >&2
    exit 64
    ;;
esac

if [[ ! -d "$root_directory" ]]; then
  echo "Terraform root does not exist: $terraform_root" >&2
  exit 66
fi

umask 077
mkdir -p "$result_directory"
temporary_directory="$(mktemp -d)"
trap 'rm -rf "$temporary_directory"' EXIT

plan_file="$temporary_directory/plan.tfplan"
plan_json="$temporary_directory/plan.json"
command_log="$temporary_directory/command.log"
changes_json="$temporary_directory/changes.json"

write_metadata() {
  local status="$1"
  local exit_code="$2"
  local phase="$3"

  jq \
    --arg root "$terraform_root" \
    --arg slug "$environment" \
    --arg environment "$environment" \
    --arg status "$status" \
    --arg phase "$phase" \
    --argjson exit_code "$exit_code" \
    '
      def action_count($action):
        [.[] | select(.actions | index($action))] | length;

      {
        root: $root,
        slug: $slug,
        status: $status,
        phase: $phase,
        exit_code: $exit_code,
        overall: {
          add: action_count("create"),
          change: action_count("update"),
          destroy: action_count("delete")
        },
        scopes: [{
          name: $environment,
          add: action_count("create"),
          change: action_count("update"),
          destroy: action_count("delete")
        }]
      }
    ' "$changes_json" >"$result_directory/metadata.json"
}

write_failure() {
  local exit_code="$1"
  local phase="$2"

  printf '[]\n' >"$changes_json"
  if [[ -s "$command_log" ]]; then
    cp "$command_log" "$result_directory/plan.txt"
  else
    printf 'The %s phase failed before Terraform produced output.\n' "$phase" \
      >"$result_directory/plan.txt"
  fi
  write_metadata failed "$exit_code" "$phase"
}

export TF_IN_AUTOMATION=1

set +e
if [[ "$state_exists" == "true" ]]; then
  terraform -chdir="$root_directory" init \
    -backend-config=use_lockfile=false \
    -input=false \
    -lock=false \
    -lockfile=readonly \
    -no-color 2>&1 | tee "$command_log"
  init_exit_code="${PIPESTATUS[0]}"
else
  backend_path="$root_directory/backend.tf"
  if [[ ! -f "$backend_path" ]]; then
    printf 'The reviewed backend configuration is missing.\n' >"$command_log"
    init_exit_code=1
  else
    mv -- "$backend_path" "$temporary_directory/backend.tf"
    terraform -chdir="$root_directory" init \
      -backend=false \
      -input=false \
      -lockfile=readonly \
      -no-color 2>&1 | tee "$command_log"
    init_exit_code="${PIPESTATUS[0]}"
  fi
fi
set -e

if [[ "$init_exit_code" -ne 0 ]]; then
  write_failure "$init_exit_code" init
  exit "$init_exit_code"
fi

set +e
selected_workspace="$(terraform -chdir="$root_directory" workspace show 2>&1)"
workspace_exit_code=$?
set -e
if [[ "$workspace_exit_code" -ne 0 || "$selected_workspace" != "$environment" ]]; then
  printf 'Expected workspace %s, got %s.\n' "$environment" "$selected_workspace" >"$command_log"
  write_failure 1 workspace
  exit 1
fi

set +e
terraform -chdir="$root_directory" validate -no-color 2>&1 | tee "$command_log"
validate_exit_code="${PIPESTATUS[0]}"
set -e
if [[ "$validate_exit_code" -ne 0 ]]; then
  write_failure "$validate_exit_code" validate
  exit "$validate_exit_code"
fi

plan_arguments=(
  -input=false
  -lock=false
  -no-color
  -detailed-exitcode
  -out="$plan_file"
)
if [[ "$state_exists" == "false" ]]; then
  plan_arguments+=(-refresh=false)
fi

set +e
terraform -chdir="$root_directory" plan "${plan_arguments[@]}" 2>&1 | tee "$command_log"
plan_exit_code="${PIPESTATUS[0]}"
set -e

if [[ "$plan_exit_code" -ne 0 && "$plan_exit_code" -ne 2 ]]; then
  write_failure "$plan_exit_code" plan
  exit "$plan_exit_code"
fi

if ! terraform -chdir="$root_directory" show -json "$plan_file" >"$plan_json"; then
  printf 'Terraform created a plan, but rendering its temporary JSON representation failed.\n' \
    >"$command_log"
  write_failure 1 render-json
  exit 1
fi

jq \
  --arg environment "$environment" \
  -f "$script_directory/summarize-plan.jq" \
  "$plan_json" >"$changes_json"

if ! terraform -chdir="$root_directory" show -no-color "$plan_file" \
  >"$result_directory/plan.txt"; then
  printf 'Terraform created a plan, but rendering its sanitized text representation failed.\n' \
    >"$command_log"
  write_failure 1 render-text
  exit 1
fi

write_metadata success "$plan_exit_code" plan

# The binary plan and raw JSON remain only inside temporary_directory and are
# deleted by the EXIT trap. Only metadata and Terraform's normal redacted text
# view are handed to the comment job.
cat "$result_directory/plan.txt"
