#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 SOURCE_DIRECTORY ENVIRONMENT RESULT_DIRECTORY" >&2
  exit 64
fi

source_directory="$(realpath "$1")"
environment="$2"
result_directory="$(realpath -m "$3")/$environment"
terraform_root="$source_directory/infra/components/static-site"
script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ "$environment" == "uat" || "$environment" == "production" ]]
[[ -d "$terraform_root" ]]

temporary_directory="$(mktemp -d)"
trap 'rm -rf "$temporary_directory"' EXIT
mkdir -p "$result_directory"

export TF_IN_AUTOMATION=1
export TF_VAR_environment="$environment"

terraform -chdir="$terraform_root" init \
  -backend-config="key=money-on-record/static-site/${environment}/terraform.tfstate" \
  -backend-config=use_lockfile=false \
  -input=false \
  -lock=false \
  -lockfile=readonly \
  -no-color

plan_file="$temporary_directory/plan.tfplan"
plan_json="$temporary_directory/plan.json"
changes_json="$temporary_directory/changes.json"

plan_arguments=(
  -input=false
  -lock=false
  -no-color
  -detailed-exitcode
  -out="$plan_file"
)

set +e
terraform -chdir="$terraform_root" plan "${plan_arguments[@]}"
plan_exit_code=$?
set -e

if [[ "$plan_exit_code" -ne 0 && "$plan_exit_code" -ne 2 ]]; then
  exit "$plan_exit_code"
fi

terraform -chdir="$terraform_root" show -json "$plan_file" >"$plan_json"
jq \
  --arg environment "$environment" \
  -f "$script_directory/summarize-plan.jq" \
  "$plan_json" >"$changes_json"
terraform -chdir="$terraform_root" show -no-color "$plan_file" \
  >"$result_directory/plan.txt"

jq \
  --arg environment "$environment" \
  --argjson exit_code "$plan_exit_code" \
  '
    def action_count($action):
      [.[] | select(.actions | index($action))] | length;

    {
      root: "infra/components/static-site",
      slug: $environment,
      status: "success",
      phase: "plan",
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

cat "$result_directory/plan.txt"
