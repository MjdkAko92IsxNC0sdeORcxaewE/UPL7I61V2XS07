import json
import os
import re
import uuid
from pathlib import Path
from typing import Literal

from live_context_schema import LiveContextError, load_and_validate, validate_candidate_live_binding


Verdict = Literal["reject", "needs_local_proof", "high_confidence_candidate", "unknown"]


NO_VULNERABILITY_MARKERS = (
    "NoVulnerability",
    "I cannot perform this security",
)


def classify_deepwiki_response(content: str | None) -> Verdict:
    if not content or not content.strip():
        return "reject"

    if any(marker in content for marker in NO_VULNERABILITY_MARKERS):
        return "reject"

    parsed = parse_json_response(content)
    if isinstance(parsed, dict):
        verdict_text = str(parsed.get("verdict") or "").strip().lower().replace(" ", "_")
        if verdict_text == "high_confidence_candidate":
            return "high_confidence_candidate"
        if verdict_text == "needs_local_proof":
            return "needs_local_proof"
        if verdict_text == "reject":
            return "reject"

    verdict_match = re.search(r"(?im)^\s*##\s*Verdict\s*$\s*([A-Z_ -]+)", content)
    verdict_text = verdict_match.group(1).strip().upper().replace(" ", "_") if verdict_match else ""

    if "HIGH_CONFIDENCE_CANDIDATE" in verdict_text or "HIGH_CONFIDENCE_CANDIDATE" in content:
        return "high_confidence_candidate"
    if "NEEDS_LOCAL_PROOF" in verdict_text or "NEEDS_LOCAL_PROOF" in content:
        return "needs_local_proof"
    if "REJECT" in verdict_text:
        return "reject"

    return "unknown"


def parse_json_response(content: str | None) -> dict | None:
    if not content:
        return None

    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def directory_for_verdict(verdict: Verdict) -> Path:
    if verdict == "high_confidence_candidate":
        return Path(os.environ.get("DEEPWIKI_CANDIDATE_DIR", "deepwiki_candidates"))
    if verdict == "needs_local_proof":
        return Path(os.environ.get("NEEDS_LOCAL_PROOF_DIR", "needs_local_proof"))
    if verdict == "reject":
        return Path(os.environ.get("REJECTED_BY_DEEPWIKI_DIR", "rejected_by_deepwiki"))
    return Path(os.environ.get("DEEPWIKI_UNKNOWN_DIR", "deepwiki_unknown"))


def rejected_by_live_gate_dir() -> Path:
    return Path(os.environ.get("REJECTED_BY_LIVE_GATE_DIR", "rejected_by_live_gate"))


def live_context_path() -> Path:
    return Path(os.environ.get("LIVE_CONTEXT_V2_PATH") or os.environ.get("LIVE_CONTEXT_PATH") or "setup/live_context_v2.json")


def live_gate_rejection_reason(parsed: dict | None, verdict: Verdict) -> str | None:
    if verdict not in ("needs_local_proof", "high_confidence_candidate"):
        return None
    if parsed is None:
        return "non-REJECT response is not strict JSON and cannot bind to live_asset_ledger"
    try:
        context = load_and_validate(live_context_path())
    except (OSError, LiveContextError, json.JSONDecodeError) as exc:
        return f"live context unavailable or invalid: {exc}"
    ok, reason = validate_candidate_live_binding(parsed, context)
    return None if ok else reason


def save_deepwiki_response(content: str, source_url: str, prefix: str = "audit") -> Path | None:
    verdict = classify_deepwiki_response(content)
    parsed = parse_json_response(content)
    live_gate_reason = live_gate_rejection_reason(parsed, verdict)
    if live_gate_reason:
        destination_dir = rejected_by_live_gate_dir()
        destination_dir.mkdir(parents=True, exist_ok=True)
        if parsed is not None:
            parsed["deepwiki_source_url"] = source_url
            parsed["deepwiki_verdict"] = verdict
            parsed["live_gate_forced_reject"] = True
            parsed["live_gate_rejection_reason"] = live_gate_reason
            filename = destination_dir / f"{prefix}_{uuid.uuid4().hex}.json"
            filename.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
            return filename

        filename = destination_dir / f"{prefix}_{uuid.uuid4().hex}.md"
        header = (
            f"<!-- deepwiki_source_url: {source_url} -->\n"
            f"<!-- deepwiki_verdict: {verdict} -->\n"
            "<!-- live_gate_forced_reject: true -->\n"
            f"<!-- live_gate_rejection_reason: {live_gate_reason} -->\n\n"
        )
        filename.write_text(header + content, encoding="utf-8")
        return filename

    if verdict == "reject" and not os.environ.get("SAVE_REJECTED_DEEPWIKI"):
        return None

    destination_dir = directory_for_verdict(verdict)
    destination_dir.mkdir(parents=True, exist_ok=True)
    if parsed is not None:
        parsed["deepwiki_source_url"] = source_url
        parsed["deepwiki_verdict"] = verdict
        filename = destination_dir / f"{prefix}_{uuid.uuid4().hex}.json"
        filename.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
        return filename

    filename = destination_dir / f"{prefix}_{uuid.uuid4().hex}.md"
    header = f"<!-- deepwiki_source_url: {source_url} -->\n<!-- deepwiki_verdict: {verdict} -->\n\n"
    filename.write_text(header + content, encoding="utf-8")
    return filename
