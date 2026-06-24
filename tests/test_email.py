# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.

from __future__ import annotations

import json
import os
import tempfile
import textwrap
from pathlib import Path

import urirun
from urirun import v2
from urirun_connector_email import (
    connector_manifest,
    extract_local_invoices,
    inbox_list,
    main,
    message_read,
    send,
    urirun_bindings,
)
import urirun_connector_email.core as core
import urirun_connector_email.thunderbird as thunderbird

ROUTE_LIST = "email://host/inbox/query/list"
ROUTE_READ = "email://host/message/query/read"
ROUTE_SEND = "email://host/message/command/send"
ROUTE_THUNDERBIRD = "email://host/local/thunderbird/query/extract_invoices"


# --- route logic (monkeypatched: NO real network) -------------------------

def test_send_requires_to() -> None:
    assert send(to="")["ok"] is False


def test_message_read_requires_uid() -> None:
    assert message_read(uid="")["ok"] is False


def test_reads_unconfigured_are_safe(monkeypatch) -> None:
    monkeypatch.delenv("EMAIL_IMAP_HOST", raising=False)
    out = inbox_list()
    assert out["ok"] is False and out["configured"] is False


def test_inbox_list_returns_dict(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("EMAIL_USER", "me@example.com")
    monkeypatch.setenv("EMAIL_PASS", "secret")
    header = b"From: a@b.com\r\nSubject: Hello\r\nDate: today\r\n\r\n"

    class _IMAP:
        def __init__(self, host, port):
            pass
        def login(self, user, pw):
            pass
        def select(self, folder, readonly=False):
            return ("OK", [b"1"])
        def search(self, charset, criteria):
            return ("OK", [b"1 2"])
        def fetch(self, mid, spec):
            return ("OK", [(b"1", header)])
        def logout(self):
            pass

    monkeypatch.setattr(core.imaplib, "IMAP4_SSL", _IMAP)
    result = inbox_list(folder="INBOX", limit=2)
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert result["messages"][0]["from"] == "a@b.com"
    assert result["messages"][0]["subject"] == "Hello"


def test_send_uses_smtp(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_USER", "me@example.com")
    monkeypatch.setenv("EMAIL_PASS", "secret")
    sent: dict = {}

    class _SMTP:
        def __init__(self, host, port):
            sent["host"] = host
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def starttls(self):
            sent["tls"] = True
        def login(self, user, pw):
            sent["user"] = user
        def send_message(self, msg):
            sent["to"] = msg["To"]

    monkeypatch.setattr(core.smtplib, "SMTP", _SMTP)
    result = send(to="x@y.com", subject="s", body="b")
    assert isinstance(result, dict)
    assert result["ok"] is True and result["sent"] is True and result["to"] == "x@y.com"
    assert sent["host"] == "smtp.example.com" and sent["tls"] is True


def test_send_resolves_password_secret_reference(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_USER", "me@example.com")
    monkeypatch.delenv("EMAIL_PASS", raising=False)  # NOT in env -> must come via reference
    monkeypatch.setenv("MY_MAIL_SECRET", "hunter2")
    seen: dict = {}

    class _SMTP:
        def __init__(self, host, port): seen["host"] = host
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, user, pw): seen["pw"] = pw
        def send_message(self, msg): pass

    monkeypatch.setattr(core.smtplib, "SMTP", _SMTP)

    # Reference resolves under an allow-list -> the real password reaches SMTP login.
    ok = send(to="x@y.com", subject="s", body="b",
              password="getv://MY_MAIL_SECRET", secret_allow="getv://MY_MAIL_SECRET")
    assert ok["ok"] is True
    assert seen["pw"] == "hunter2"

    # Same reference without the allow-list is denied by policy (deny-by-default).
    denied = send(to="x@y.com", subject="s", body="b", password="getv://MY_MAIL_SECRET")
    assert denied["ok"] is False
    assert "denied by policy" in denied["error"]


# --- local thunderbird extraction tests -----------------------------------

def _make_mbox(dir_path: str, mbox_name: str, messages: list[str]) -> str:
    """Write an mbox file with the given raw messages into dir_path."""
    mbox_path = os.path.join(dir_path, mbox_name)
    with open(mbox_path, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(msg)
    return mbox_path


def _invoice_message(filename: str = "invoice.pdf", payload: str = "JVBERi0x") -> str:
    return textwrap.dedent(f"""\
        From sender@test.com Mon Mar  2 10:00:00 2026
        From: sender@test.com
        To: user@example.com
        Subject: Invoice 123
        Date: Mon, 2 Mar 2026 10:00:00 +0000
        MIME-Version: 1.0
        Content-Type: multipart/mixed; boundary="B"

        --B
        Content-Type: application/pdf; name="{filename}"
        Content-Disposition: attachment; filename="{filename}"
        Content-Transfer-Encoding: base64

        {payload}
        --B--
    """)


def test_extract_local_invoices_missing_profile() -> None:
    result = extract_local_invoices(profile_dir="/nonexistent/profile")
    assert result["ok"] is False


def test_extract_local_invoices_from_synthetic_mbox() -> None:
    """Build a minimal Thunderbird-like profile tree and verify extraction."""
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_dir = os.path.join(tmpdir, "profile")
        downloads_dir = os.path.join(tmpdir, "downloads")
        os.makedirs(downloads_dir)

        # Create ImapMail/example.com/ with an INBOX mbox
        imap_dir = os.path.join(profile_dir, "ImapMail", "example.com")
        os.makedirs(imap_dir)

        # Write a prefs.js so example.com maps to user@example.com
        with open(os.path.join(profile_dir, "prefs.js"), "w") as f:
            f.write('user_pref("mail.server.server1.directory", "/fake/ImapMail/example.com");\n')
            f.write('user_pref("mail.server.server1.name", "user@example.com");\n')

        # Build a synthetic mbox with one invoice message (with PDF attachment)
        invoice_msg = textwrap.dedent("""\
            From sender@test.com Mon Mar  2 10:00:00 2026
            From: sender@test.com
            To: user@example.com
            Subject: Faktura nr 123/2026
            Date: Mon, 2 Mar 2026 10:00:00 +0000
            MIME-Version: 1.0
            Content-Type: multipart/mixed; boundary="BOUNDARY123"

            --BOUNDARY123
            Content-Type: text/plain; charset="utf-8"

            Please find the invoice attached.
            --BOUNDARY123
            Content-Type: application/pdf; name="invoice-123.pdf"
            Content-Disposition: attachment; filename="invoice-123.pdf"
            Content-Transfer-Encoding: base64

            JVBERi0xLjQKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+PgplbmRvYmoK
            --BOUNDARY123--
        """)

        # A non-invoice message (should be skipped)
        normal_msg = textwrap.dedent("""\
            From other@test.com Mon Mar  3 11:00:00 2026
            From: other@test.com
            To: user@example.com
            Subject: Hello there
            Date: Mon, 3 Mar 2026 11:00:00 +0000
            Content-Type: text/plain

            Just a regular email with no invoice content.
        """)

        _make_mbox(imap_dir, "INBOX", [invoice_msg, normal_msg])

        result = extract_local_invoices(
            start_date="2026-03-01",
            end_date="2026-04-01",
            downloads_dir=downloads_dir,
            profile_dir=profile_dir,
            search_terms=["faktura", "invoice"],
        )

        assert result["ok"] is True
        assert result["scanned_mboxs"] >= 1
        assert result["saved_count"] >= 1

        # Default office workflow shape: downloads/YYYY.MM/<files>
        month_dir = os.path.join(downloads_dir, "2026.03")
        assert os.path.isdir(month_dir), f"Expected directory {month_dir}"
        files = os.listdir(month_dir)
        assert any("invoice" in f.lower() for f in files), f"Expected invoice file, got: {files}"
        assert result["stats"]["2026.03"]["saved"] == 1


def test_extract_local_invoices_can_group_by_account() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_dir = os.path.join(tmpdir, "profile")
        downloads_dir = os.path.join(tmpdir, "downloads")
        imap_dir = os.path.join(profile_dir, "ImapMail", "example.com")
        os.makedirs(imap_dir)
        with open(os.path.join(profile_dir, "prefs.js"), "w") as f:
            f.write('user_pref("mail.server.server1.directory", "/fake/ImapMail/example.com");\n')
            f.write('user_pref("mail.server.server1.name", "user@example.com");\n')
        invoice_msg = textwrap.dedent("""\
            From sender@test.com Mon Mar  2 10:00:00 2026
            From: sender@test.com
            To: user@example.com
            Subject: Invoice 123
            Date: Mon, 2 Mar 2026 10:00:00 +0000
            MIME-Version: 1.0
            Content-Type: multipart/mixed; boundary="B"

            --B
            Content-Type: application/pdf; name="invoice.pdf"
            Content-Disposition: attachment; filename="invoice.pdf"
            Content-Transfer-Encoding: base64

            JVBERi0x
            --B--
        """)
        _make_mbox(imap_dir, "INBOX", [invoice_msg])

        result = extract_local_invoices(
            start_date="2026-03-01",
            end_date="2026-04-01",
            downloads_dir=downloads_dir,
            profile_dir=profile_dir,
            group_by_account=True,
        )

        assert result["ok"] is True
        assert os.path.isfile(os.path.join(downloads_dir, "2026.03", "user@example.com", "invoice.pdf"))


def test_extract_local_invoices_dry_run_and_json_report() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_dir = os.path.join(tmpdir, "profile")
        downloads_dir = os.path.join(tmpdir, "downloads")
        report_path = os.path.join(tmpdir, "report.json")
        imap_dir = os.path.join(profile_dir, "ImapMail", "example.com")
        os.makedirs(imap_dir)
        with open(os.path.join(profile_dir, "prefs.js"), "w") as f:
            f.write('user_pref("mail.server.server1.directory", "/fake/ImapMail/example.com");\n')
            f.write('user_pref("mail.server.server1.name", "user@example.com");\n')
        _make_mbox(imap_dir, "INBOX", [_invoice_message()])

        result = extract_local_invoices(
            start_date="2026-03-01",
            end_date="2026-04-01",
            downloads_dir=downloads_dir,
            profile_dir=profile_dir,
            dry_run=True,
            json_out=report_path,
        )

        assert result["ok"] is True
        assert result["dryRun"] is True
        assert result["saved_count"] == 0
        assert result["stats"]["2026.03"]["attachments"] == 1
        assert not os.path.exists(os.path.join(downloads_dir, "2026.03", "invoice.pdf"))
        assert json.load(open(report_path, encoding="utf-8"))["dryRun"] is True


def test_extract_local_invoices_dedupes_attachment_payloads() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_dir = os.path.join(tmpdir, "profile")
        downloads_dir = os.path.join(tmpdir, "downloads")
        imap_dir = os.path.join(profile_dir, "ImapMail", "example.com")
        os.makedirs(imap_dir)
        with open(os.path.join(profile_dir, "prefs.js"), "w") as f:
            f.write('user_pref("mail.server.server1.directory", "/fake/ImapMail/example.com");\n')
            f.write('user_pref("mail.server.server1.name", "user@example.com");\n')
        _make_mbox(
            imap_dir,
            "INBOX",
            [_invoice_message("invoice-a.pdf", "JVBERi0x"), _invoice_message("invoice-b.pdf", "JVBERi0x")],
        )

        result = extract_local_invoices(
            start_date="2026-03-01",
            end_date="2026-04-01",
            downloads_dir=downloads_dir,
            profile_dir=profile_dir,
        )

        assert result["ok"] is True
        assert result["stats"]["2026.03"]["saved"] == 1
        assert result["stats"]["2026.03"]["duplicates"] == 1


def test_extract_local_invoices_no_matches_in_range() -> None:
    """Messages outside the date range should not be extracted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_dir = os.path.join(tmpdir, "profile")
        downloads_dir = os.path.join(tmpdir, "downloads")
        os.makedirs(downloads_dir)
        imap_dir = os.path.join(profile_dir, "ImapMail", "test.com")
        os.makedirs(imap_dir)

        # Write a prefs.js
        with open(os.path.join(profile_dir, "prefs.js"), "w") as f:
            f.write('user_pref("mail.server.server1.directory", "/fake/ImapMail/test.com");\n')
            f.write('user_pref("mail.server.server1.name", "info@test.com");\n')

        # Message from January (outside March-June range)
        old_msg = textwrap.dedent("""\
            From sender@test.com Mon Jan  5 10:00:00 2026
            From: sender@test.com
            To: info@test.com
            Subject: Faktura styczeń
            Date: Mon, 5 Jan 2026 10:00:00 +0000
            Content-Type: text/plain

            Old invoice.
        """)
        _make_mbox(imap_dir, "INBOX", [old_msg])

        result = extract_local_invoices(
            start_date="2026-03-01",
            end_date="2026-06-01",
            downloads_dir=downloads_dir,
            profile_dir=profile_dir,
        )
        assert result["ok"] is True
        assert result["saved_count"] == 0
        assert result["totals"]["messages"] == 1


def test_account_mapping_from_prefs() -> None:
    """Verify _get_account_mapping parses prefs.js correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prefs_path = os.path.join(tmpdir, "prefs.js")
        with open(prefs_path, "w") as f:
            f.write('user_pref("mail.server.server1.directory", "/home/user/.thunderbird/profile/ImapMail/sapletta.com");\n')
            f.write('user_pref("mail.server.server1.name", "tomasz@sapletta.com");\n')
            f.write('user_pref("mail.server.server6.directory", "/home/user/.thunderbird/profile/ImapMail/sapletta-2.com");\n')
            f.write('user_pref("mail.server.server6.name", "tomasz@sapletta.pl");\n')

        mapping = thunderbird._get_account_mapping(Path(tmpdir))
        assert mapping["sapletta.com"] == "tomasz@sapletta.com"
        assert mapping["sapletta-2.com"] == "tomasz@sapletta.pl"


# --- isolated handler bindings --------------------------------------------

def test_bindings_are_isolated_handlers() -> None:
    b = urirun_bindings()["bindings"]
    assert set(b) == {ROUTE_LIST, ROUTE_READ, ROUTE_SEND, ROUTE_THUNDERBIRD}
    # registry-portable in-process handlers: run out-of-process via urirun.exec
    assert b[ROUTE_LIST]["adapter"] == "local-function-subprocess"
    assert b[ROUTE_LIST]["python"]["module"] == "urirun_connector_email.core"
    assert b[ROUTE_LIST]["python"]["export"] == "inbox_list"
    assert b[ROUTE_READ]["python"]["export"] == "message_read"
    assert b[ROUTE_SEND]["python"]["export"] == "send"
    assert b[ROUTE_THUNDERBIRD]["python"]["export"] == "extract_local_invoices"
    for route in (ROUTE_LIST, ROUTE_READ, ROUTE_SEND, ROUTE_THUNDERBIRD):
        assert "argv" not in b[route]
    assert b[ROUTE_LIST]["inputSchema"]["properties"]["folder"]["default"] == "INBOX"
    assert b[ROUTE_THUNDERBIRD]["inputSchema"]["properties"]["start_date"]["default"] == "2026-03-01"
    json.dumps(urirun_bindings())  # serializable: no live ref leaks


def test_compiles_and_routes_present() -> None:
    registry = urirun.compile_registry(json.loads(json.dumps(urirun_bindings())))
    uris = {r["uri"] for r in urirun.list_routes(registry)}
    assert {ROUTE_LIST, ROUTE_READ, ROUTE_SEND, ROUTE_THUNDERBIRD} <= uris


def test_runtime_executes_from_compiled_registry() -> None:
    # the whole point: a serialized->compiled registry still runs the route.
    # unconfigured -> ok False, configured False, no network attempted.
    registry = urirun.compile_registry(json.loads(json.dumps(urirun_bindings())))
    env = v2.run(ROUTE_LIST, registry, payload={"folder": "INBOX", "limit": 5},
                 mode="execute", policy=urirun.policy(allow=["email://*"]))
    assert env["ok"] is True
    data = urirun.result_data(env)
    assert data["ok"] is False and data["configured"] is False


# --- manifest -------------------------------------------------------------

def test_manifest_prose_plus_derived_routes() -> None:
    m = connector_manifest()
    assert m["id"] == "email"
    assert m["uriSchemes"] == ["email"]
    assert set(m["routes"]) == {ROUTE_LIST, ROUTE_READ, ROUTE_SEND, ROUTE_THUNDERBIRD}
    assert m["summary"] and m["keywords"]  # prose preserved
    assert "thunderbird" in m["keywords"]
    json.dumps(m)


# --- console-script CLI ---------------------------------------------------

def test_cli_bindings_and_manifest(capsys) -> None:
    assert main(["bindings"]) == 0
    assert ROUTE_SEND in json.loads(capsys.readouterr().out)["bindings"]
    assert main(["manifest"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "email"
