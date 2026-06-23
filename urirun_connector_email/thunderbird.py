# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.

"""Local Thunderbird mailbox helpers for the email connector."""

from __future__ import annotations

import datetime as _dt
import email
import hashlib
import json
import os
import re
import time
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


DEFAULT_PROFILE_ROOTS = (
    "~/.var/app/net.thunderbird.Thunderbird/.thunderbird",
    "~/.var/app/org.mozilla.Thunderbird/.thunderbird",
    "~/.thunderbird",
)

DEFAULT_TERMS = (
    "faktura",
    "faktury",
    "fakture",
    "fakturę",
    "invoice",
    "vat",
    "rachunek",
    "proforma",
    "fv",
    "bill",
    "billing",
    "receipt",
    "paragon",
    "platnosc",
    "płatność",
    "oplata",
    "opłata",
)

DEFAULT_EXTENSIONS = (
    ".pdf",
    ".xml",
    ".zip",
    ".jpg",
    ".jpeg",
    ".png",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
)

SKIP_SUFFIXES = (
    ".msf",
    ".ini",
    ".dat",
    ".json",
    ".sqlite",
    ".sqlite-wal",
    ".sqlite-shm",
)


def export_invoices(
    *,
    start_date: str = "2026-03-01",
    end_date: str = "2026-06-01",
    months: str | list[str] | None = None,
    downloads_dir: str = "~/Downloads",
    profile_dir: str = "",
    profile_roots: str | list[str] | None = None,
    search_terms: str | list[str] | None = None,
    extensions: str | list[str] | None = None,
    dry_run: bool = False,
    group_by_account: bool = False,
    json_out: str = "",
    include_details: bool = False,
    dedupe: bool = True,
    save_message_without_attachment: bool = False,
) -> dict[str, Any]:
    """Extract invoice-like attachments from local Thunderbird mbox files.

    The default output shape is ``downloads_dir/YYYY.MM/files`` because this is
    the office workflow used on the Lenovo node. Set ``group_by_account=True``
    to add an account subdirectory below each month.
    """

    started = time.monotonic()
    try:
        t_start = _parse_date(start_date)
        t_end = _parse_date(end_date)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if t_start >= t_end:
        return {"ok": False, "error": "start_date must be earlier than end_date"}

    try:
        month_set = _months_from_input(months) if months else _months_between(t_start, t_end)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not month_set:
        return {"ok": False, "error": "months resolved to an empty range"}

    terms = tuple(_normalise_text(v) for v in _split_values(search_terms, DEFAULT_TERMS))
    suffixes = tuple(_normalise_extension(v) for v in _split_values(extensions, DEFAULT_EXTENSIONS))
    dest = Path(os.path.expanduser(downloads_dir)).resolve()
    profiles = _discover_profiles(profile_dir=profile_dir, profile_roots=profile_roots)
    if not profiles:
        target = profile_dir or ", ".join(DEFAULT_PROFILE_ROOTS)
        return {"ok": False, "error": f"Thunderbird profile not found: {target}"}

    stats = _empty_stats(month_set)
    details: list[dict[str, Any]] = []
    seen_hashes = _existing_hashes(dest, month_set) if dedupe and not dry_run else set()
    seen_mboxes: set[tuple[str, int]] = set()
    seen_inodes: set[tuple[int, int]] = set()
    totals = {"profiles": len(profiles), "mboxes": 0, "messages": 0, "errors": 0, "skippedMboxes": 0}

    for profile in profiles:
        account_mapping = _get_account_mapping(profile)
        for mbox_path in _iter_mboxes(profile, seen_mboxes=seen_mboxes, seen_inodes=seen_inodes):
            totals["mboxes"] += 1
            try:
                _scan_mbox(
                    mbox_path,
                    profile,
                    account_mapping,
                    start=t_start,
                    end=t_end,
                    month_set=month_set,
                    terms=terms,
                    suffixes=suffixes,
                    dest=dest,
                    stats=stats,
                    totals=totals,
                    details=details,
                    seen_hashes=seen_hashes,
                    dry_run=dry_run,
                    group_by_account=group_by_account,
                    include_details=include_details,
                    dedupe=dedupe,
                    save_message_without_attachment=save_message_without_attachment,
                )
            except Exception as exc:  # noqa: BLE001 - keep scanning other mboxes
                totals["errors"] += 1
                if include_details:
                    details.append({"type": "error", "path": str(mbox_path), "error": str(exc)})

    saved_count = sum(v["saved"] for v in stats.values())
    result: dict[str, Any] = {
        "ok": totals["errors"] == 0,
        "dryRun": dry_run,
        "dest": str(dest),
        "months": sorted(month_set),
        "profiles": [str(p) for p in profiles],
        "stats": {k: stats[k] for k in sorted(stats)},
        "totals": totals,
        "scanned_mboxes": totals["mboxes"],
        "scanned_mboxs": totals["mboxes"],
        "saved_count": saved_count,
        "elapsedSec": round(time.monotonic() - started, 3),
    }
    if include_details:
        result["details"] = details

    if json_out:
        out_path = Path(os.path.expanduser(json_out))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result["jsonOut"] = str(out_path)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def _parse_date(value: str) -> _dt.datetime:
    try:
        return _dt.datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid date {value!r}; use YYYY-MM-DD") from exc


def _months_between(start: _dt.datetime, end: _dt.datetime) -> set[str]:
    current = _dt.datetime(start.year, start.month, 1, tzinfo=_dt.timezone.utc)
    out = set()
    while current < end:
        out.add(current.strftime("%Y.%m"))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return out


def _months_from_input(value: str | list[str] | tuple[str, ...] | None) -> set[str]:
    out = set()
    for item in _split_values(value, ()):
        item = item.strip()
        if not item:
            continue
        if re.fullmatch(r"\d{4}-\d{2}", item):
            item = item.replace("-", ".")
        if not re.fullmatch(r"\d{4}\.\d{2}", item):
            raise ValueError(f"invalid month {item!r}; use YYYY.MM")
        out.add(item)
    return out


def _split_values(value: str | list[str] | tuple[str, ...] | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None or value == "":
        return default
    if isinstance(value, (list, tuple)):
        return tuple(str(v).strip() for v in value if str(v).strip())
    return tuple(v.strip() for v in re.split(r"[,;\n]", str(value)) if v.strip())


def _normalise_extension(value: str) -> str:
    value = value.strip().lower()
    return value if value.startswith(".") else f".{value}"


def _normalise_text(value: str) -> str:
    return value.casefold()


def _empty_stats(months: set[str]) -> dict[str, dict[str, int]]:
    return {
        month: {"messages": 0, "candidateMessages": 0, "attachments": 0, "saved": 0, "duplicates": 0}
        for month in months
    }


def _discover_profiles(*, profile_dir: str, profile_roots: str | list[str] | None) -> list[Path]:
    candidates: list[Path] = []
    if profile_dir:
        candidates.append(Path(os.path.expanduser(profile_dir)))
    else:
        roots = _split_values(profile_roots, DEFAULT_PROFILE_ROOTS)
        for root_raw in roots:
            root = Path(os.path.expanduser(root_raw))
            if not root.exists():
                continue
            if (root / "prefs.js").is_file():
                candidates.append(root)
                continue
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / "prefs.js").is_file():
                    candidates.append(child)

    out: list[Path] = []
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if (resolved / "prefs.js").is_file() and str(resolved) not in seen:
            seen.add(str(resolved))
            out.append(resolved)
    return out


def _get_account_mapping(profile_dir: Path) -> dict[str, str]:
    prefs_path = profile_dir / "prefs.js"
    if not prefs_path.exists():
        return {}

    dir_prefs: dict[str, str] = {}
    name_prefs: dict[str, str] = {}
    for line in prefs_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m_dir = re.search(r'user_pref\("mail\.server\.(server\d+)\.directory",\s*"(.*?)"\);', line)
        if m_dir:
            server_id, dir_path = m_dir.group(1), m_dir.group(2)
            dir_prefs[server_id] = os.path.basename(dir_path)
            continue
        m_name = re.search(r'user_pref\("mail\.server\.(server\d+)\.name",\s*"(.*?)"\);', line)
        if m_name:
            server_id, name = m_name.group(1), m_name.group(2)
            name_prefs[server_id] = name

    return {dir_name: name_prefs[server_id] for server_id, dir_name in dir_prefs.items() if server_id in name_prefs}


def _iter_mboxes(
    profile: Path,
    *,
    seen_mboxes: set[tuple[str, int]],
    seen_inodes: set[tuple[int, int]],
):
    for root_name in ("ImapMail", "Mail"):
        root = profile / root_name
        if not root.is_dir():
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for filename in files:
                lower = filename.lower()
                if lower.endswith(SKIP_SUFFIXES):
                    continue
                path = Path(current) / filename
                try:
                    stat = path.stat()
                    if stat.st_size <= 0:
                        continue
                    inode_key = (stat.st_dev, stat.st_ino)
                    if inode_key in seen_inodes:
                        continue
                    logical_key = (str(path.relative_to(profile)), stat.st_size)
                    if logical_key in seen_mboxes:
                        continue
                    with path.open("rb") as fh:
                        if fh.read(5) != b"From ":
                            continue
                except OSError:
                    continue
                seen_inodes.add(inode_key)
                seen_mboxes.add(logical_key)
                yield path


def _scan_mbox(
    mbox_path: Path,
    profile: Path,
    account_mapping: dict[str, str],
    *,
    start: _dt.datetime,
    end: _dt.datetime,
    month_set: set[str],
    terms: tuple[str, ...],
    suffixes: tuple[str, ...],
    dest: Path,
    stats: dict[str, dict[str, int]],
    totals: dict[str, int],
    details: list[dict[str, Any]],
    seen_hashes: set[str],
    dry_run: bool,
    group_by_account: bool,
    include_details: bool,
    dedupe: bool,
    save_message_without_attachment: bool,
) -> None:
    msg_lines: list[str] = []
    headers: list[str] = []
    in_headers = False

    def flush() -> None:
        nonlocal msg_lines, headers
        if not msg_lines:
            return
        totals["messages"] += 1
        date_value = _header_value(headers, "date")
        msg_date = _safe_message_date(date_value)
        if not msg_date or not (start <= msg_date < end):
            msg_lines = []
            headers = []
            return
        month = msg_date.strftime("%Y.%m")
        if month not in month_set:
            msg_lines = []
            headers = []
            return
        stats[month]["messages"] += 1
        raw = "".join(msg_lines)
        message = email.message_from_string(raw)
        account = _account_for_mbox(mbox_path, profile, account_mapping)
        _process_message(
            message,
            mbox_path=mbox_path,
            account=account,
            month=month,
            date_value=date_value,
            terms=terms,
            suffixes=suffixes,
            dest=dest,
            stats=stats,
            details=details,
            seen_hashes=seen_hashes,
            dry_run=dry_run,
            group_by_account=group_by_account,
            include_details=include_details,
            dedupe=dedupe,
            save_message_without_attachment=save_message_without_attachment,
        )
        msg_lines = []
        headers = []

    with mbox_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("From "):
                flush()
                msg_lines = [line]
                headers = []
                in_headers = True
                continue
            if msg_lines:
                msg_lines.append(line)
                if in_headers:
                    if line.strip() == "":
                        in_headers = False
                    else:
                        headers.append(line)
        flush()


def _header_value(headers: list[str], name: str) -> str:
    prefix = f"{name}:"
    for line in headers:
        if line.casefold().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def _safe_message_date(value: str) -> _dt.datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:  # noqa: BLE001
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def _account_for_mbox(mbox_path: Path, profile: Path, account_mapping: dict[str, str]) -> str:
    try:
        parts = mbox_path.relative_to(profile).parts
    except ValueError:
        parts = mbox_path.parts
    folder = parts[1] if len(parts) >= 2 else "Unknown"
    return account_mapping.get(folder, folder)


def _process_message(
    message: Message,
    *,
    mbox_path: Path,
    account: str,
    month: str,
    date_value: str,
    terms: tuple[str, ...],
    suffixes: tuple[str, ...],
    dest: Path,
    stats: dict[str, dict[str, int]],
    details: list[dict[str, Any]],
    seen_hashes: set[str],
    dry_run: bool,
    group_by_account: bool,
    include_details: bool,
    dedupe: bool,
    save_message_without_attachment: bool,
) -> None:
    subject = _decode_header_value(message.get("Subject"))
    body = _plain_text(message, limit=12000)
    subject_or_body_hit = _contains_term(f"{subject}\n{body}", terms)
    attachments = list(_attachments(message))
    attachment_hit = any(_contains_term(name, terms) for name, _payload in attachments)
    candidate = subject_or_body_hit or attachment_hit
    if not candidate:
        return

    stats[month]["candidateMessages"] += 1
    accepted = [
        (name, payload)
        for name, payload in attachments
        if Path(name).suffix.casefold() in suffixes
    ]

    if not accepted and save_message_without_attachment:
        payload = f"Subject: {subject}\nDate: {date_value}\n\n{body}".encode("utf-8")
        accepted = [(f"{subject[:60] or 'message'}.txt", payload)]

    if not accepted:
        return

    for filename, payload in accepted:
        digest = hashlib.sha256(payload).hexdigest()
        if dedupe and digest in seen_hashes:
            stats[month]["duplicates"] += 1
            continue
        if dedupe:
            seen_hashes.add(digest)
        stats[month]["attachments"] += 1

        target_dir = dest / month
        if group_by_account:
            target_dir = target_dir / _safe_path_name(account, fallback="Unknown")
        target_path = _available_path(target_dir, filename)
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(payload)
            stats[month]["saved"] += 1
        if include_details:
            details.append(
                {
                    "month": month,
                    "date": date_value,
                    "subject": subject,
                    "mailbox": str(mbox_path),
                    "account": account,
                    "file": str(target_path),
                    "dryRun": dry_run,
                }
            )


def _decode_header_value(value: str | None) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:  # noqa: BLE001
        return value or ""


def _plain_text(message: Message, *, limit: int) -> str:
    chunks: list[str] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_type() != "text/plain":
            continue
        if "attachment" in str(part.get("Content-Disposition", "")).lower():
            continue
        payload = part.get_payload(decode=True) or b""
        try:
            chunks.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
        except LookupError:
            chunks.append(payload.decode("utf-8", "replace"))
        if sum(len(c) for c in chunks) >= limit:
            break
    return "\n".join(chunks)[:limit]


def _attachments(message: Message):
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        if not filename:
            continue
        decoded = _decode_header_value(filename)
        payload = part.get_payload(decode=True)
        if payload:
            yield decoded, payload


def _contains_term(text: str, terms: tuple[str, ...]) -> bool:
    normalised = _normalise_text(text)
    return any(term and term in normalised for term in terms)


def _safe_path_name(value: str, *, fallback: str) -> str:
    safe = "".join(c for c in value if c.isalnum() or c in "._- @").strip()
    return safe or fallback


def _available_path(target_dir: Path, filename: str) -> Path:
    safe_name = _safe_path_name(filename, fallback="attachment")
    path = target_dir / safe_name
    if not path.exists():
        return path
    stem = path.stem or "attachment"
    suffix = path.suffix
    counter = 1
    while True:
        candidate = target_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _existing_hashes(dest: Path, months: set[str]) -> set[str]:
    hashes = set()
    for month in months:
        month_dir = dest / month
        if not month_dir.exists():
            continue
        for path in month_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
            except OSError:
                continue
    return hashes
