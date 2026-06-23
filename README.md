# urirun-connector-email

Email connector for [ifURI](https://ifuri.com) / urirun: read an inbox (IMAP),
send mail (SMTP), and extract invoice attachments from local Thunderbird
mailboxes — all through `email://` routes.

Catalog: <https://connect.ifuri.com/connectors/email>

| URI | Operation |
| --- | --- |
| `email://host/inbox/query/list` | list recent message headers (IMAP, read) |
| `email://host/message/query/read` | read one message body (IMAP, read) |
| `email://host/message/command/send` | send a message (SMTP, gated) |
| `email://host/local/thunderbird/query/extract_invoices` | extract invoices from local Thunderbird mailboxes |

Each route is a typed `@conn.handler(..., isolated=True)`: the function signature
is the input schema and the function body is the implementation — no argv
template, no `_exec.py`, no dispatcher. `isolated=True` runs the route
out-of-process via urirun's shared runner, so the binding stays
registry-portable (it runs straight from a compiled/served registry with only
the package importable). The IMAP/SMTP routes reach a remote mail server, so the
safety gate is urirun's `--execute` on the registry runner — not a function
param.

## Credentials (env, never the manifest)

```bash
export EMAIL_IMAP_HOST=imap.example.com EMAIL_SMTP_HOST=smtp.example.com
export EMAIL_USER=me@example.com EMAIL_PASS='app-password'
urirun-email list --limit 5
urirun-email send --to a@b.com --subject hi --body hello
```

Without credentials the routes return a fast "not configured" (`ok: false`)
result without touching the network, so the connector installs and validates
anywhere.

## Local Thunderbird Invoice Extraction

The `local/thunderbird/query/extract_invoices` route reads Thunderbird mbox
files directly from disk, identifies invoice-related messages by subject, body
and attachment keywords, and saves invoice-like attachments into monthly
directories:

```
~/Downloads/
  ├── 2026.03/
  │   ├── Invoice-001.pdf
  │   └── Receipt-002.pdf
  ├── 2026.04/
  └── 2026.05/
```

By default the route auto-discovers profiles under common Thunderbird locations:

- `~/.var/app/net.thunderbird.Thunderbird/.thunderbird`
- `~/.var/app/org.mozilla.Thunderbird/.thunderbird`
- `~/.thunderbird`

Set `profile_dir` to scan one explicit profile, or `profile_roots` to provide a
comma-separated list of Thunderbird roots. If `group_by_account=true`, account
names are resolved from Thunderbird's `prefs.js` and files are saved below
`YYYY.MM/account@email/`.

The extractor is designed for long local mailboxes: it streams mbox files,
deduplicates duplicate profile roots and duplicate attachment payloads by
SHA-256, supports `dry_run`, and can write a compact JSON report.

### Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `start_date` | `2026-03-01` | Start of date range (YYYY-MM-DD, UTC) |
| `end_date` | `2026-06-01` | End of date range (YYYY-MM-DD, UTC) |
| `months` | derived from date range | Optional comma-separated `YYYY.MM` allowlist |
| `downloads_dir` | `~/Downloads` | Root output directory |
| `profile_dir` | empty | Explicit Thunderbird profile path |
| `profile_roots` | common Flatpak/native roots | Comma-separated Thunderbird roots |
| `search_terms` | built-in invoice terms | Comma-separated keywords |
| `extensions` | `pdf,xml,zip,jpg,png,doc,xls,csv...` | Attachment extensions to keep |
| `dry_run` | `false` | Count and report without writing files |
| `group_by_account` | `false` | Save under `YYYY.MM/account/` |
| `json_out` | empty | Optional report path |
| `include_details` | `false` | Include per-file details in the result |
| `dedupe` | `true` | Skip repeated attachment payloads |

### Usage in a flow

```yaml
- id: extract_invoices
  uri: email://laptop/local/thunderbird/query/extract_invoices
  payload:
    start_date: "2026-03-01"
    end_date: "2026-06-01"
    months: "2026.03,2026.04,2026.05"
    downloads_dir: "~/Downloads"
    json_out: "~/Downloads/invoice_export_2026.03-2026.05_report.json"
```

### CLI

```bash
urirun-email extract_invoices \
  --start_date 2026-03-01 \
  --end_date 2026-06-01 \
  --months 2026.03,2026.04,2026.05 \
  --json_out ~/Downloads/invoice_export_2026.03-2026.05_report.json
```

## Examples

Runnable walkthrough: [`examples/`](examples/) — `./examples/triage-inbox.sh`.

## Test

```bash
pip install -e ".[test]" && pytest -q   # IMAP/SMTP are mocked
```
