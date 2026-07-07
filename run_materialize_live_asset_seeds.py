"""Write Workflow 7 scanner seeds from the UPV2 live asset ledger."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from live_context_schema import load_and_validate


def _safe(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def _seed_for_row(context: dict, row: dict, index: int) -> dict:
    asset_label = row.get("symbol") or row.get("asset_address") or f"ledger_{index}"
    return {
        "schema_version": "upv2-live-asset-scan-seed-v1",
        "seed_type": "live_asset_ledger",
        "ledger_index": index,
        "target": context["blueprint"],
        "chain": context["chain"],
        "chain_id": context["chain_id"],
        "block_number": context["block_number"],
        "block_hash": context["block_hash"],
        "ledger_row": row,
        "scanner_instruction": (
            "Find only critical fund extraction, protocol value drain, reward extraction, or unfair reward access "
            f"paths that let an unprivileged attacker extract this exact live {asset_label} ledger row beyond entitlement. "
            "Reject admin-only, role-only, governance, key-compromise, future-deposit, unbacked reward, DoS, griefing, "
            "liveness, or accounting-only claims."
        ),
        "required_non_reject_binding": {
            "ledger_type": "live_asset_ledger",
            "ledger_index": index,
            "asset_address": row.get("asset_address"),
            "holder_contract": row.get("holder_contract"),
            "current_balance_raw": row.get("raw_balance"),
            "current_block_number": context["block_number"],
            "current_block_hash": context["block_hash"],
            "json_source_path": row.get("json_source_path"),
        },
    }


def materialize_live_asset_seeds(context_path: str = "setup/live_context_v2.json", out_dir: str = "scanned") -> list[Path]:
    context = load_and_validate(context_path)
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for index, row in enumerate(context.get("live_asset_ledger", [])):
        if not isinstance(row, dict):
            continue
        holder = _safe(row.get("holder_contract"))
        asset = _safe(row.get("asset_address"))
        symbol = _safe(row.get("symbol"))
        filename = f"live_asset_seed__{_safe(context['chain'])}__{holder}__{asset}_{symbol}.json"
        path = destination / filename
        path.write_text(json.dumps(_seed_for_row(context, row, index), indent=2) + "\n", encoding="utf-8")
        written.append(path)

    if not written:
        raise RuntimeError("no live_asset_ledger rows were available to materialize")

    for path in written:
        print(f"wrote live asset scanner seed: {path}")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize Workflow 7 live asset scanner seeds.")
    parser.add_argument("--context", default="setup/live_context_v2.json")
    parser.add_argument("--out-dir", default="scanned")
    args = parser.parse_args()

    materialize_live_asset_seeds(context_path=args.context, out_dir=args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
