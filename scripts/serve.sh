#!/usr/bin/env sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec python3 -m http.server 8765 --bind 0.0.0.0 --directory "$project_dir/dist"
