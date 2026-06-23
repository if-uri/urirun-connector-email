# Changelog

## [0.3.0] - 2026-06-23

### Changed
- Replaced the simple single-profile Thunderbird extractor with the Lenovo-tested
  exporter: auto-discovers common Thunderbird profile roots, scans multiple
  profiles, deduplicates duplicate mboxes and attachment payloads, writes into
  monthly `YYYY.MM` folders, supports `dry_run`, `json_out`, explicit `months`,
  optional `group_by_account`, and compact stats.
- The route remains
  `email://host/local/thunderbird/query/extract_invoices`, so existing flows keep
  working while gaining the new parameters.

### Added
- Regression tests for monthly output, account grouping, dry-run JSON reports,
  and duplicate attachment payloads.

## [0.2.0] - 2026-06-23

### Added
- `email://host/local/thunderbird/query/extract_invoices` — extract invoices and
  attachments from a local Thunderbird profile. Parses `prefs.js` to resolve
  internal directory names (e.g. `sapletta-2.com`) to real email addresses
  (e.g. `tomasz@sapletta.pl`). Saves into `~/Downloads/YYYY-MM/account@email/`.
  Streaming line-by-line mbox parser handles multi-GB mailboxes without blocking.
- Full test coverage for the new route: synthetic mbox, date-range filtering,
  prefs.js mapping, missing-profile error path.
- Updated manifest, README, and connector keywords.

## [0.1.0] - 2026-06-21

### Added
- Initial Email connector: `email://inbox/query/list`, `.../message/query/read`
  (IMAP, read) and `.../message/command/send` (SMTP, dry-run by default). Built on
  the urirun connector SDK; credentials from the environment. CLI, manifest,
  pytest suite (IMAP/SMTP mocked), smoke, CI and the `urirun.bindings` entry point.
