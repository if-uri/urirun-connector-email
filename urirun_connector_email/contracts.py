# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""Route contracts for the Email connector."""
from __future__ import annotations

from urirun_connectors_toolkit.contract_gate import Contract

_HEAD = {"ok": "const:true", "connector": "const:email"}
_REMOTE_ERRORS = ("unauthenticated", "unreachable")


CONTRACTS: dict[str, Contract] = {
    "inbox/query/list": Contract(
        version="v1",
        effect="query",
        inp={
            "folder": "?str",
            "limit": "?int",
            "user": "?str",
            "password": "?str",
            "secret_allow": "?str",
        },
        out={
            **_HEAD,
            "folder": "str",
            "count": "int",
            "messages": [
                {"uid": "str", "from": "str", "subject": "str", "date": "str"}
            ],
        },
        errors=_REMOTE_ERRORS,
        examples=(
            {
                "payload": {"folder": "INBOX", "limit": 2},
                "result": {
                    "ok": True,
                    "connector": "email",
                    "folder": "INBOX",
                    "count": 1,
                    "messages": [
                        {
                            "uid": "2",
                            "from": "a@b.com",
                            "subject": "Hello",
                            "date": "today",
                        }
                    ],
                },
            },
        ),
    ),
    "message/query/read": Contract(
        version="v1",
        effect="query",
        inp={
            "uid": "?str",
            "folder": "?str",
            "max": "?int",
            "user": "?str",
            "password": "?str",
            "secret_allow": "?str",
        },
        out={
            **_HEAD,
            "uid": "str",
            "from": "str",
            "subject": "str",
            "date": "str",
            "body": "str",
        },
        errors=("precondition-unmet", *_REMOTE_ERRORS),
        examples=(
            {
                "payload": {"uid": "2", "folder": "INBOX", "max": 4000},
                "result": {
                    "ok": True,
                    "connector": "email",
                    "uid": "2",
                    "from": "a@b.com",
                    "subject": "Hello",
                    "date": "today",
                    "body": "Message body",
                },
            },
        ),
    ),
    "message/command/send": Contract(
        version="v1",
        effect="command",
        reversible=False,
        inp={
            "to": "?str",
            "subject": "?str",
            "body": "?str",
            "cc": "?str",
            "user": "?str",
            "password": "?str",
            "secret_allow": "?str",
        },
        out={
            **_HEAD,
            "action": "const:send",
            "sent": "const:true",
            "to": "str",
            "subject": "str",
        },
        errors=("precondition-unmet", *_REMOTE_ERRORS),
        examples=(
            {
                "payload": {"to": "x@y.com", "subject": "s", "body": "b"},
                "result": {
                    "ok": True,
                    "connector": "email",
                    "action": "send",
                    "sent": True,
                    "to": "x@y.com",
                    "subject": "s",
                },
            },
        ),
    ),
    "local/thunderbird/query/extract_invoices": Contract(
        version="v1",
        effect="query",
        inp={
            "start_date": "?str",
            "end_date": "?str",
            "months": "?str",
            "downloads_dir": "?str",
            "profile_dir": "?str",
            "profile_roots": "?str",
            "search_terms": "?str",
            "extensions": "?str",
            "dry_run": "?bool",
            "group_by_account": "?bool",
            "json_out": "?str",
            "include_details": "?bool",
            "dedupe": "?bool",
            "save_message_without_attachment": "?bool",
        },
        out={
            **_HEAD,
            "dryRun": "bool",
            "dest": "str",
            "months": ["str"],
            "profiles": ["str"],
            "stats": "obj",
            "totals": "obj",
            "scanned_mboxes": "int",
            "scanned_mboxs": "int",
            "saved_count": "int",
            "elapsedSec": "num",
        },
        errors=("precondition-unmet", "unreachable", "unknown"),
        examples=(
            {
                "payload": {
                    "start_date": "2026-03-01",
                    "end_date": "2026-04-01",
                    "profile_dir": "/tmp/profile",
                    "downloads_dir": "/tmp/downloads",
                },
                "result": {
                    "ok": True,
                    "connector": "email",
                    "dryRun": False,
                    "dest": "/tmp/downloads",
                    "months": ["2026.03"],
                    "profiles": ["/tmp/profile"],
                    "stats": {
                        "2026.03": {
                            "messages": 1,
                            "candidateMessages": 1,
                            "attachments": 1,
                            "saved": 1,
                            "duplicates": 0,
                        }
                    },
                    "totals": {
                        "profiles": 1,
                        "mboxes": 1,
                        "messages": 1,
                        "errors": 0,
                        "skippedMboxes": 0,
                    },
                    "scanned_mboxes": 1,
                    "scanned_mboxs": 1,
                    "saved_count": 1,
                    "elapsedSec": 0.01,
                },
            },
        ),
    ),
}
