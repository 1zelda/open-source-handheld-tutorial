import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from pathlib import Path

BASE = Path(__file__).resolve().parent
RECEIPT = BASE / "A1_授权申请发送回执_复核_2026-11-25.json"
POLICY = BASE / "source_policy_v1.json"
OUT = BASE / "A1_发送前核验_2026-11-26.json"
SPECS = [
    {
        "id": "A1_GRID",
        "review": "A1_GRID_商用授权咨询_发送复核_2026-11-25.eml",
        "to": "sales@grid.gg",
        "subject": "Commercial licensing enquiry - local esports fact-checking knowledge base",
        "source_id": "E05",
        "commercial_use": "denied",
        "phrases": ["commercial", "local", "redistribute", "permission", "confirmed", "GRID"],
    },
    {
        "id": "A1_Liquipedia",
        "review": "A1_Liquipedia_LPDB授权咨询_发送复核_2026-11-25.eml",
        "to": "contact@liquipedia.net",
        "subject": "LPDB access and commercial use enquiry - local fact-checking knowledge base",
        "source_id": "E06",
        "commercial_use": "unknown",
        "phrases": ["LPDB", "commercial", "403", "redistribute", "permission", "confirmed"],
    },
    {
        "id": "A1_OpenDota",
        "review": "A1_OpenDota_数据用途咨询_发送复核_2026-11-25.eml",
        "to": "support@opendota.com",
        "subject": "OpenDota API data use and commercial licensing enquiry",
        "source_id": "E09",
        "commercial_use": "unknown",
        "phrases": ["OpenDota", "commercial", "code licence", "redistribute", "permission", "confirmed"],
    },
]


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".tmp", dir=path.parent)
    os.close(fd)
    tmp = Path(name)
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def body_text(msg):
    if msg.is_multipart():
        return "\n".join(part.get_content() for part in msg.walk()
                         if part.get_content_type() == "text/plain")
    return msg.get_content()


def main():
    parser = argparse.ArgumentParser(description="只读核验 A1 三封授权申请邮件，不发送")
    parser.add_argument("--open-review", action="store_true", help="核验后打开三封未发送复核副本")
    args = parser.parse_args()

    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    policy_doc = json.loads(POLICY.read_text(encoding="utf-8"))
    sources = {row["source_id"]: row for row in policy_doc["sources"]}
    receipt_drafts = {row["id"]: row for row in receipt["drafts"]}
    results = []
    defects = []

    for spec in SPECS:
        path = BASE / spec["review"]
        row = {"id": spec["id"], "review_copy": str(path), "defects": []}
        if not path.is_file():
            row["defects"].append("review_copy_missing")
            results.append(row)
            defects.extend(f"{spec['id']}:review_copy_missing" for _ in (0,))
            continue
        raw = path.read_bytes()
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        body = body_text(msg)
        recipients = [addr for _, addr in getaddresses(msg.get_all("To", []))]
        receipt_row = receipt_drafts.get(spec["id"], {})
        if recipients != [spec["to"]]:
            row["defects"].append("recipient_mismatch")
        if str(msg.get("Subject", "")).strip() != spec["subject"]:
            row["defects"].append("subject_mismatch")
        if str(msg.get("X-Unsent", "")).strip() != "1":
            row["defects"].append("not_marked_unsent")
        if receipt_row.get("to") != spec["to"] or receipt_row.get("review_copy") != spec["review"]:
            row["defects"].append("receipt_binding_mismatch")
        if receipt_row.get("x_unsent") != 1 or receipt_row.get("sent_at") is not None or receipt_row.get("reply_received") is not False:
            row["defects"].append("receipt_not_unsent_draft")
        if re.search(r"\[[^\]]+\]|<[^>]+>|\b(?:TODO|TBD|PLACEHOLDER)\b", body, re.I):
            row["defects"].append("unresolved_placeholder")
        for phrase in spec["phrases"]:
            if phrase.casefold() not in body.casefold():
                row["defects"].append(f"missing_phrase:{phrase}")
        if len(body.strip()) < 500:
            row["defects"].append("body_too_short")
        source = sources.get(spec["source_id"])
        if source is None:
            row["defects"].append("policy_source_missing")
        else:
            if source.get("commercial_use") != spec["commercial_use"]:
                row["defects"].append(f"policy_semantic_mismatch:{spec['source_id']}")
            row["policy"] = {
                "source_id": spec["source_id"],
                "commercial_use": source.get("commercial_use"),
                "automated_access": source.get("automated_access"),
                "local_retention": source.get("local_retention"),
            }
        row.update({
            "to": recipients,
            "subject": str(msg.get("Subject", "")).strip(),
            "from_present": bool(msg.get("From")),
            "x_unsent": str(msg.get("X-Unsent", "")).strip(),
            "body_chars": len(body.strip()),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
        results.append(row)
        defects.extend(f"{spec['id']}:{item}" for item in row["defects"])

    identity = receipt.get("identity_inputs", {})
    identity_blockers = []
    for key in ("channel_url", "signature_or_legal_name", "contact_email"):
        if not identity.get(key):
            identity_blockers.append(f"identity_missing:{key}")
    contact = identity.get("contact_email")
    if contact and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact):
        identity_blockers.append("identity_invalid:contact_email")

    account_count = int(receipt.get("channel_probe", {}).get("outlook_accounts", 0))
    blockers = defects + identity_blockers
    if account_count < 1:
        blockers.append("sender_account_missing")

    report = {
        "schema_version": 1,
        "checked_at": datetime.now().astimezone().isoformat(),
        "status": "ready_to_send" if not blockers else "blocked",
        "ready_to_send": not blockers,
        "sending_performed": False,
        "external_network_calls": 0,
        "receipt": str(RECEIPT),
        "policy": str(POLICY),
        "drafts": results,
        "identity_inputs": identity,
        "account_snapshot": {
            "source": "receipt_snapshot",
            "outlook_accounts": account_count,
            "last_probe_at": receipt.get("last_probe_at"),
        },
        "defects": defects,
        "identity_blockers": identity_blockers,
        "blockers": blockers,
        "next_action": "补齐频道 URL、署名/主体名称、联系邮箱并配置真实发件账号；重新运行本脚本后，人工核对 From 与正文再发送。",
    }
    atomic_json(OUT, report)
    print(json.dumps({"status": report["status"], "ready_to_send": report["ready_to_send"],
                      "blockers": blockers, "report": str(OUT)}, ensure_ascii=False, indent=2))
    if args.open_review and not defects:
        for spec in SPECS:
            os.startfile(BASE / spec["review"])
    return 0 if report["ready_to_send"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
