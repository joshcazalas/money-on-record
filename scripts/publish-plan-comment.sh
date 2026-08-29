#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 COMMENT_FILE REPOSITORY PULL_REQUEST_NUMBER" >&2
  exit 64
fi

comment_file="$1"
repository="$2"
pull_request_number="$3"
marker='<!-- money-on-record-terraform-plan -->'

if [[ ! -s "$comment_file" ]]; then
  echo "Comment file is missing or empty." >&2
  exit 66
fi

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "GH_TOKEN is required." >&2
  exit 65
fi

temporary_directory="$(mktemp -d)"
trap 'rm -rf "$temporary_directory"' EXIT

comments_file="$temporary_directory/comments.json"
payload_file="$temporary_directory/payload.json"

gh api --paginate --slurp \
  "repos/${repository}/issues/${pull_request_number}/comments?per_page=100" \
  >"$comments_file"

comment_id="$(
  jq -r \
    --arg marker "$marker" \
    '[
      add[]
      | select(.user.login == "github-actions[bot]")
      | select(.user.type == "Bot")
      | select(.body | contains($marker))
    ]
    | sort_by(.id)
    | first
    | .id // empty' \
    "$comments_file"
)"

jq -Rs '{body: .}' "$comment_file" >"$payload_file"

if [[ -n "$comment_id" ]]; then
  gh api --silent \
    --method PATCH \
    "repos/${repository}/issues/comments/${comment_id}" \
    --input "$payload_file"
  echo "Updated sticky Terraform plan comment $comment_id."
else
  gh api --silent \
    --method POST \
    "repos/${repository}/issues/${pull_request_number}/comments" \
    --input "$payload_file"
  echo "Created sticky Terraform plan comment."
fi
