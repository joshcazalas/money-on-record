#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
component_root="${repository_root}/infra/components/static-site"

run_workspace_test() {
  local workspace="$1"
  local test_file="$2"

  echo "Testing Terraform workspace contract: ${workspace}"
  (
    cd "$component_root"
    TF_WORKSPACE="$workspace" terraform test \
      -no-color \
      -filter="tests/${test_file}.tftest.hcl"
  )
}

run_workspace_test default default
run_workspace_test unsupported unknown
run_workspace_test uat uat
run_workspace_test production production
