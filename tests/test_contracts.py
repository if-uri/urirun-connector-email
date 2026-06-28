# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
from __future__ import annotations

import pytest

pytest.importorskip("urirun_connectors_toolkit.contract_gate")
pytest.importorskip("urirun_contract.contract_lint")

import urirun_connector_email as mail  # noqa: E402
from urirun_connector_email import core  # noqa: E402
from urirun_connector_email.contracts import CONTRACTS  # noqa: E402
from urirun_connectors_toolkit.contract_gate import conform, envelope_violation  # noqa: E402
from urirun_contract.contract_lint import lint_handler_signatures  # noqa: E402


ROUTE_SEND = "email://host/message/command/send"


def test_contracts_conform():
    conform(CONTRACTS)


def test_contracts_match_live_handler_signatures():
    problems = lint_handler_signatures(CONTRACTS, mail.urirun_bindings(), conn_uri=core.conn.uri)
    assert problems == []


def test_bindings_carry_contract_metadata():
    bindings = mail.urirun_bindings()["bindings"]
    assert set(CONTRACTS) == {uri.removeprefix("email://host/") for uri in bindings}
    contract = bindings[ROUTE_SEND]["meta"]["contract"]
    assert contract["effect"] == "command"
    assert contract["reversible"] is False
    assert contract["output"]["sent"] == "const:true"


def test_mocked_send_output_satisfies_contract(monkeypatch):
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_USER", "me@example.com")
    monkeypatch.setenv("EMAIL_PASS", "secret")

    class _SMTP:
        def __init__(self, host, port):
            self.host = host

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            return None

        def login(self, user, password):
            return None

        def send_message(self, message):
            return None

    monkeypatch.setattr(core.smtplib, "SMTP", _SMTP)
    env = mail.send(to="x@y.com", subject="s", body="b")
    bad = envelope_violation(CONTRACTS["message/command/send"], env)
    assert bad is None, f"send output violates contract: {bad}\nenvelope={env}"
