#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${ROOT_DIR}/storage/receipts"

if [[ ! -d "${TARGET_DIR}" ]]; then
  echo "Receipts directory not found: ${TARGET_DIR}"
  exit 0
fi

# Remove uploaded receipt images older than 5 days.
find "${TARGET_DIR}" -type f -mtime +5 -print -delete
