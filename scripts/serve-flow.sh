#!/usr/bin/env sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
site_port=${1:-8765}
case "$site_port" in ''|*[!0-9]*) echo 'Use a numeric HTTP port.' >&2; exit 1;; esac
exec python3 -m http.server "$site_port" --bind 0.0.0.0 --directory "$project_dir/flow-studio"
