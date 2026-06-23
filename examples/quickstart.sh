#!/usr/bin/env bash
# email: install once, then run — auto-discovered, no registry path.
set -euo pipefail
urirun install urirun-connector-email            # local dev: pip install -e .
urirun run 'email://host/inbox/query/list' --payload '{}' --execute --allow 'email://*'
