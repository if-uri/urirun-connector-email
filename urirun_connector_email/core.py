# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.

"""Email connector for urirun — IMAP read + SMTP send as email:// routes.

Routes match the connect.ifuri.com contract:

* ``email://host/inbox/query/list``     -- list recent message headers (IMAP)
* ``email://host/message/query/read``   -- read one message body (IMAP)
* ``email://host/message/command/send`` -- send a message (SMTP)

Each route is declared once with a typed ``@conn.handler``: the function
signature becomes the input schema and the function body *is* the
implementation — no argv template, no ``_exec.py``, no ``run_route``
dispatcher, no ``@command`` stubs. ``isolated=True`` runs the route
out-of-process through the shared ``python -m urirun.exec`` runner, so the
binding stays **registry-portable**: it executes from a compiled/served
registry (``urirun compile`` / ``urirun run``) with only the package importable
— no console-script install and no per-connector shim.

All three routes touch a remote mail server, so the safety gate is urirun's
``--execute`` on the registry runner (not a function param). When the route is
not configured it returns an ``ok: false`` dict quickly without reaching the
network. Hosts come from the environment (``EMAIL_IMAP_HOST``, ``EMAIL_SMTP_HOST``,
``EMAIL_IMAP_PORT`` 993, ``EMAIL_SMTP_PORT`` 587, optional ``EMAIL_FROM``). The
**password is addressed by reference** — pass ``password=getv://EMAIL_PASS`` or
``secret://keyring/email#pass`` plus ``secret_allow`` and it is resolved through the
urirun secrets layer (deny-by-default); an empty ``password`` falls back to the
``EMAIL_PASS`` env var, so existing setups keep working.

The manifest stays prose-only; ``routes``/``uriSchemes`` are derived from the
declared handlers.
"""

from __future__ import annotations

import email
import imaplib
import os
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from typing import Any

import urirun

from .thunderbird import export_invoices as _export_thunderbird_invoices


CONNECTOR_ID = "email"
conn = urirun.connector(CONNECTOR_ID, scheme="email")


# --- config + helpers (real implementation) -------------------------------

# The password is addressed by reference (never embedded); the shared resolver lives in the
# urirun SDK so every connector honours the secrets layer identically.
_resolve_secret = urirun.resolve_secret


def _imap_cfg(user: str = "", password: str = "", secret_allow: str = "") -> dict | None:
    host = os.getenv("EMAIL_IMAP_HOST")
    if not host:
        return None
    return {"host": host, "port": int(os.getenv("EMAIL_IMAP_PORT", "993")),
            "user": user or os.getenv("EMAIL_USER", ""),
            "password": _resolve_secret(password, secret_allow) or os.getenv("EMAIL_PASS", "")}


def _smtp_cfg(user: str = "", password: str = "", secret_allow: str = "") -> dict | None:
    host = os.getenv("EMAIL_SMTP_HOST")
    if not host:
        return None
    resolved_user = user or os.getenv("EMAIL_USER", "")
    return {"host": host, "port": int(os.getenv("EMAIL_SMTP_PORT", "587")),
            "user": resolved_user,
            "password": _resolve_secret(password, secret_allow) or os.getenv("EMAIL_PASS", ""),
            "from": os.getenv("EMAIL_FROM") or resolved_user}


def _decode(value: str | None) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:  # noqa: BLE001
        return value or ""


def _connect_imap(cfg: dict) -> imaplib.IMAP4_SSL:
    client = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
    client.login(cfg["user"], cfg["password"])
    return client


def _not_configured(kind: str) -> dict[str, Any]:
    env = "EMAIL_IMAP_HOST" if kind == "imap" else "EMAIL_SMTP_HOST"
    return urirun.fail(f"set {env} + EMAIL_USER + EMAIL_PASS to use this route",
                       connector=CONNECTOR_ID, configured=False)


def _message_text(message: email.message.Message, limit: int) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", "replace")[:limit]
        return ""
    payload = message.get_payload(decode=True) or b""
    return payload.decode(message.get_content_charset() or "utf-8", "replace")[:limit]


# --- route handlers: schema derived from the signature, run isolated -------

@conn.handler("inbox/query/list", isolated=True,
              meta={"label": "List recent inbox messages"})
def inbox_list(folder: str = "INBOX", limit: int = 10,
               user: str = "", password: str = "", secret_allow: str = "") -> dict[str, Any]:
    """List recent message headers from an IMAP folder.

    ``password`` may be a secret *reference* (``getv://EMAIL_PASS`` / ``secret://keyring/...``)
    resolved through the secrets layer under ``secret_allow`` (deny-by-default); falls back to
    ``EMAIL_PASS`` env when empty. ``user`` overrides ``EMAIL_USER``.
    """
    try:
        cfg = _imap_cfg(user, password, secret_allow)
    except PermissionError as exc:
        return urirun.fail(f"credential denied by policy (add it to secret_allow): {exc}", connector=CONNECTOR_ID)
    if not cfg:
        return _not_configured("imap")
    try:
        client = _connect_imap(cfg)
        client.select(folder, readonly=True)
        _, data = client.search(None, "ALL")
        ids = data[0].split()[-int(limit):]
        messages = []
        for mid in reversed(ids):
            _, msg_data = client.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            header = email.message_from_bytes(msg_data[0][1])
            messages.append({"uid": mid.decode(), "from": _decode(header.get("From")),
                             "subject": _decode(header.get("Subject")), "date": header.get("Date", "")})
        client.logout()
        return urirun.ok(connector=CONNECTOR_ID, folder=folder, count=len(messages), messages=messages)
    except Exception as exc:  # noqa: BLE001 - report IMAP failures as JSON
        return urirun.fail(str(exc), connector=CONNECTOR_ID)


@conn.handler("message/query/read", isolated=True,
              meta={"label": "Read one message"})
def message_read(uid: str = "", folder: str = "INBOX", max: int = 4000,
                 user: str = "", password: str = "", secret_allow: str = "") -> dict[str, Any]:
    """Read one message body from an IMAP folder. ``password``/``secret_allow`` as in ``inbox_list``."""
    if not uid:
        return urirun.fail("uid is required", connector=CONNECTOR_ID)
    try:
        cfg = _imap_cfg(user, password, secret_allow)
    except PermissionError as exc:
        return urirun.fail(f"credential denied by policy (add it to secret_allow): {exc}", connector=CONNECTOR_ID)
    if not cfg:
        return _not_configured("imap")
    try:
        client = _connect_imap(cfg)
        client.select(folder, readonly=True)
        _, msg_data = client.fetch(uid.encode(), "(RFC822)")
        message = email.message_from_bytes(msg_data[0][1])
        client.logout()
        return urirun.ok(connector=CONNECTOR_ID, uid=uid,
                         **{"from": _decode(message.get("From"))},
                         subject=_decode(message.get("Subject")),
                         date=message.get("Date", ""), body=_message_text(message, int(max)))
    except Exception as exc:  # noqa: BLE001
        return urirun.fail(str(exc), connector=CONNECTOR_ID)


@conn.handler("message/command/send", isolated=True,
              meta={"label": "Send a message"})
def send(to: str = "", subject: str = "", body: str = "", cc: str = "",
         user: str = "", password: str = "", secret_allow: str = "") -> dict[str, Any]:
    """Send a message over SMTP. ``password``/``secret_allow`` as in ``inbox_list``."""
    if not to:
        return urirun.fail("to is required", connector=CONNECTOR_ID)
    try:
        cfg = _smtp_cfg(user, password, secret_allow)
    except PermissionError as exc:
        return urirun.fail(f"credential denied by policy (add it to secret_allow): {exc}", connector=CONNECTOR_ID)
    if not cfg:
        return urirun.fail("set EMAIL_SMTP_HOST + EMAIL_USER + EMAIL_PASS to send", connector=CONNECTOR_ID)
    message = EmailMessage()
    message["From"] = cfg["from"]
    message["To"] = to
    if cc:
        message["Cc"] = cc
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
            server.starttls()
            if cfg["user"]:
                server.login(cfg["user"], cfg["password"])
            server.send_message(message)
        return urirun.ok(connector=CONNECTOR_ID, action="send", sent=True, to=to, subject=subject)
    except Exception as exc:  # noqa: BLE001
        return urirun.fail(str(exc), connector=CONNECTOR_ID, action="send")


@conn.handler("local/thunderbird/query/extract_invoices", isolated=True,
              meta={"label": "Extract invoices from local Thunderbird profile"})
def extract_local_invoices(
    start_date: str = "2026-03-01",
    end_date: str = "2026-06-01",
    months: str = "",
    downloads_dir: str = "~/Downloads",
    profile_dir: str = "",
    profile_roots: str = "",
    search_terms: str = "",
    extensions: str = "",
    dry_run: bool = False,
    group_by_account: bool = False,
    json_out: str = "",
    include_details: bool = False,
    dedupe: bool = True,
    save_message_without_attachment: bool = False,
) -> dict[str, Any]:
    """Extract invoice-like attachments from local Thunderbird mailboxes."""
    result = _export_thunderbird_invoices(
        start_date=start_date,
        end_date=end_date,
        months=months,
        downloads_dir=downloads_dir,
        profile_dir=profile_dir,
        profile_roots=profile_roots,
        search_terms=search_terms,
        extensions=extensions,
        dry_run=dry_run,
        group_by_account=group_by_account,
        json_out=json_out,
        include_details=include_details,
        dedupe=dedupe,
        save_message_without_attachment=save_message_without_attachment,
    )
    if result.get("ok"):
        return urirun.ok(connector=CONNECTOR_ID, **{k: v for k, v in result.items() if k != "ok"})
    return urirun.fail(str(result.get("error", "Thunderbird invoice extraction failed")),
                       connector=CONNECTOR_ID,
                       **{k: v for k, v in result.items() if k not in {"ok", "error"}})


# --- authoring surface: bindings / manifest / CLI --------------------------

def urirun_bindings() -> dict[str, Any]:
    """Serializable v2 bindings for this connector (entry point: urirun.bindings)."""
    return conn.bindings()


def connector_manifest() -> dict[str, Any]:
    """Full manifest: prose (connector.manifest.json) + routes/uriSchemes/
    adapterKinds/examples derived from the handlers."""
    return conn.manifest(urirun.load_manifest(__package__))


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point: subcommands + dispatch derived from handlers."""
    return conn.cli(argv, manifest_prose=urirun.load_manifest(__package__))


if __name__ == "__main__":
    import sys

    raise SystemExit(main())
