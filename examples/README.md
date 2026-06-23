# email connector — examples

IMAP read + SMTP send (gated by creds; reads are safe).

## Install
```bash
urirun install urirun-connector-email
```
`urirun install` resolves catalog ids via connect.ifuri.com; `--catalog <url>` points at a
local/on-prem registry; a full package name / git URL / path falls back to `pip install`.

## Run
```bash
# IMAP read + SMTP send (gated by creds; reads are safe) (read)
urirun run 'email://host/inbox/query/list' --payload '{}' --execute --allow 'email://*'

# preview without running (dry-run): drop --execute
urirun run 'email://host/inbox/query/list' --payload '{}' --allow 'email://*'
```

## Extract Thunderbird invoices on a node
```bash
urirun run 'email://laptop/local/thunderbird/query/extract_invoices' \
  --payload '{
    "start_date": "2026-03-01",
    "end_date": "2026-06-01",
    "months": "2026.03,2026.04,2026.05",
    "downloads_dir": "~/Downloads",
    "json_out": "~/Downloads/invoice_export_2026.03-2026.05_report.json"
  }' \
  --execute \
  --allow 'email://*'
```

Use `"dry_run": true` first when testing a new workstation. The route scans
local Thunderbird mbox files, so it must run on the node where Thunderbird stores
the profile.

## Inspect the runtime (no path — like error:// / log://)
```bash
urirun list | grep 'email://'                                   # this connector's routes
urirun run 'registry://local/routes/query/list' --payload '{"scheme":"email"}' --allow 'registry://*'
urirun run 'registry://local/bindings/query/show' --payload '{"uri":"email://host/inbox/query/list"}' --allow 'registry://*'   # full typed contract
urirun errors                                                      # recent runtime errors (error://)
```

## Generate a client / API surface from the binding
```bash
urirun discover | urirun gen openapi - --out openapi.json   # OpenAPI 3 (one path per route)
urirun discover | urirun gen proto   - --out service.proto  # protobuf + gRPC (typed rpc per route)
urirun discover | urirun gen client  - --out client.py      # typed Python client
```
