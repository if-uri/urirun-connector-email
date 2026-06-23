#!/usr/bin/env bash
# Email: list the inbox and try a send — both safe without credentials
# (unconfigured routes return a fast "not configured" result, no network).
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1) list inbox (safe: 'not configured' unless EMAIL_IMAP_HOST set) =="
urirun-connector-email list --limit 5 | python3 -c 'import json,sys;d=json.load(sys.stdin);print("   configured:",d.get("configured", True),"| ok:",d["ok"])'

echo "== 2) send (safe: 'not configured' unless EMAIL_SMTP_HOST set — nothing leaves) =="
urirun-connector-email send --to a@b.com --subject "Re: hi" --body "thanks!" | python3 -c 'import json,sys;d=json.load(sys.stdin);print("   ok:",d["ok"],"| error:",d.get("error",""))'

echo "== 3) route surface =="
urirun-connector-email bindings | urirun validate -
