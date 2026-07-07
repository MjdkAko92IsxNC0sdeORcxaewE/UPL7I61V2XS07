"""UPV2 live-context and candidate live-ledger validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


SCHEMA_VERSION = "upv2-live-context-v2"
BRIDGEINDEX_PROXY = "0x3cd6fb6b0cddd3610f0f4769aa7bb686cd4a4b55"
BRIDGEINDEX_IMPLEMENTATION = "0x1d85a38d4a3ea8a6ae74f185a1df267704e7a748"
BRIDGEINDEX_BLOCK_HASH_108581678 = "0x122165d97b1c836f8a4a62c475b2c379cc8c57299f6f92926f00c54b1f8f3f25"


class LiveContextError(ValueError):
    pass


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise LiveContextError(f"{path} must contain a JSON object")
    return data


def _as_positive_int(value: Any) -> bool:
    try:
        return int(str(value), 10) > 0
    except (TypeError, ValueError):
        return False


def _ledger_rows(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = context.get("live_asset_ledger")
    if not isinstance(rows, list):
        raise LiveContextError("live_asset_ledger must be a list")
    return [row for row in rows if isinstance(row, dict)]


def build_bridgeindex_upv2_context(source: Dict[str, Any]) -> Dict[str, Any]:
    target = source.get("target") if isinstance(source.get("target"), dict) else {}
    balances = source.get("balances") if isinstance(source.get("balances"), dict) else {}
    native = balances.get("native") if isinstance(balances.get("native"), dict) else {}
    erc20_rows = balances.get("erc20") if isinstance(balances.get("erc20"), list) else []
    block_number = int(source.get("latest_block") or source.get("block_number") or 0)
    block_hash = source.get("block_hash") or ""
    if block_number == 108581678 and not block_hash:
        block_hash = BRIDGEINDEX_BLOCK_HASH_108581678

    holder = _norm(target.get("proxy_address") or target.get("address") or BRIDGEINDEX_PROXY)
    implementation = _norm(target.get("implementation_address") or target.get("source_address") or BRIDGEINDEX_IMPLEMENTATION)
    commands = [
        {
            "purpose": "fetch captured block hash",
            "command": f"eth_getBlockByNumber({hex(block_number)}, false)",
            "observed_value": block_hash,
        },
        {
            "purpose": "fetch native proxy balance",
            "command": f"eth_getBalance({holder}, {hex(block_number)})",
            "observed_value": str(native.get("raw") or target.get("native_balance_wei") or "0"),
        },
    ]

    ledger: List[Dict[str, Any]] = []
    native_raw = str(native.get("raw") or target.get("native_balance_wei") or "0")
    if _as_positive_int(native_raw):
        ledger.append(
            {
                "asset_type": "native",
                "asset_address": "native",
                "symbol": native.get("symbol") or target.get("native_symbol") or "BNB",
                "decimals": 18,
                "holder_contract": holder,
                "holder_role": "proxy",
                "raw_balance": native_raw,
                "human_balance": str(native.get("human") or ""),
                "usd_value": "unknown",
                "balance_source": "eth_getBalance",
                "source_command": commands[-1]["command"],
                "json_source_path": "$.balances.native.raw",
                "block_number": block_number,
                "block_hash": block_hash,
                "nonzero": True,
            }
        )

    for index, row in enumerate(erc20_rows):
        if not isinstance(row, dict):
            continue
        raw = str(row.get("raw_balance") or "0")
        token = _norm(row.get("token"))
        if not token or not _as_positive_int(raw):
            continue
        command = f"balanceOf({holder}) on {token} at {hex(block_number)}"
        commands.append({"purpose": f"fetch {row.get('symbol') or token} proxy balance", "command": command, "observed_value": raw})
        ledger.append(
            {
                "asset_type": "erc20",
                "asset_address": token,
                "symbol": row.get("symbol") or "",
                "decimals": row.get("decimals", 18),
                "holder_contract": holder,
                "holder_role": "proxy",
                "raw_balance": raw,
                "human_balance": str(row.get("human_balance") or ""),
                "usd_value": str(row.get("usd_value") or "unknown"),
                "balance_source": "balanceOf",
                "source_command": command,
                "json_source_path": f"$.balances.erc20[{index}].raw_balance",
                "block_number": block_number,
                "block_hash": block_hash,
                "nonzero": True,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at_utc": source.get("captured_at") or source.get("generated_at") or "",
        "chain": source.get("chain") or "bsc",
        "chain_id": source.get("chain_id") or 56,
        "block_number": block_number,
        "block_hash": block_hash,
        "rpc_endpoint_label": source.get("rpc_endpoint_used") or "",
        "blueprint": {
            "project_name": "BridgeIndex",
            "source_repo": "incjanta/BridgeIndex",
            "target_label": f"BridgeIndex BotBridge BSC proxy at {holder}",
            "paid_impact_focus": "fund extraction and reward extraction",
        },
        "identity_gate": {
            "target_matches_blueprint": holder == BRIDGEINDEX_PROXY,
            "proxy_address": holder,
            "implementation_address": implementation,
            "source_files": source.get("source_identity", {}).get("source_files", []),
        },
        "contracts": [
            {
                "name": source.get("source_identity", {}).get("contract_name") or "BotBridge",
                "address": holder,
                "implementation_address": implementation,
                "deployment_kind": target.get("deployment_kind") or "proxy",
            }
        ],
        "live_asset_ledger": ledger,
        "reward_liability_ledger": [],
        "event_derived_keys": [],
        "parameterized_views": source.get("parameterized_views") or {},
        "freshness": {
            "max_age_blocks": 3000,
            "is_fresh": True,
            "must_refresh_before_deepwiki": False,
        },
        "commands_used": commands,
        "source_snapshot": source,
    }


def validate_live_context(context: Dict[str, Any]) -> None:
    if context.get("schema_version") != SCHEMA_VERSION:
        raise LiveContextError(f"schema_version must be {SCHEMA_VERSION}")
    if context.get("chain") != "bsc" or int(context.get("chain_id") or 0) != 56:
        raise LiveContextError("BridgeIndex UPV2 context must be BSC chain_id 56")
    if not context.get("block_number") or not context.get("block_hash"):
        raise LiveContextError("block_number and block_hash are required")
    identity = context.get("identity_gate") if isinstance(context.get("identity_gate"), dict) else {}
    if _norm(identity.get("proxy_address")) != BRIDGEINDEX_PROXY:
        raise LiveContextError("proxy_address does not match BridgeIndex")
    if _norm(identity.get("implementation_address")) != BRIDGEINDEX_IMPLEMENTATION:
        raise LiveContextError("implementation_address does not match BridgeIndex")
    if not identity.get("target_matches_blueprint"):
        raise LiveContextError("identity_gate.target_matches_blueprint must be true")
    freshness = context.get("freshness") if isinstance(context.get("freshness"), dict) else {}
    if freshness.get("must_refresh_before_deepwiki") or not freshness.get("is_fresh"):
        raise LiveContextError("live context is marked stale or refresh-required")
    rows = _ledger_rows(context)
    if not rows:
        raise LiveContextError("live_asset_ledger must contain at least one row")
    for index, row in enumerate(rows):
        if not row.get("holder_contract") or not row.get("asset_address"):
            raise LiveContextError(f"ledger row {index} is missing holder_contract or asset_address")
        if not row.get("block_hash") or row.get("block_number") != context.get("block_number"):
            raise LiveContextError(f"ledger row {index} must bind to context block number/hash")
        if not row.get("source_command") or not row.get("json_source_path"):
            raise LiveContextError(f"ledger row {index} must include source_command and json_source_path")
        if not row.get("nonzero") or not _as_positive_int(row.get("raw_balance")):
            raise LiveContextError(f"ledger row {index} must have a current nonzero raw_balance")


def load_and_validate(path: str | Path) -> Dict[str, Any]:
    context = _load_json(Path(path))
    validate_live_context(context)
    return context


def write_validation_report(context_path: str | Path, out: str | Path) -> Dict[str, Any]:
    context = load_and_validate(context_path)
    report = {
        "schema_version": "upv2-live-context-validation-v1",
        "context_path": str(context_path),
        "valid": True,
        "project_name": context["blueprint"]["project_name"],
        "source_repo": context["blueprint"]["source_repo"],
        "chain": context["chain"],
        "chain_id": context["chain_id"],
        "block_number": context["block_number"],
        "block_hash": context["block_hash"],
        "live_asset_ledger_count": len(context.get("live_asset_ledger", [])),
        "reward_liability_ledger_count": len(context.get("reward_liability_ledger", [])),
    }
    output = Path(out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def validate_candidate_live_binding(candidate: Dict[str, Any], context: Dict[str, Any]) -> Tuple[bool, str]:
    verdict = str(candidate.get("verdict") or "").upper()
    if verdict == "REJECT":
        return True, ""
    try:
        validate_live_context(context)
    except LiveContextError as exc:
        return False, f"invalid live context: {exc}"

    exploited = candidate.get("exploited_live_value")
    delta = candidate.get("attacker_value_delta")
    gates = candidate.get("live_balance_hard_gates")
    if not isinstance(exploited, dict):
        return False, "missing exploited_live_value"
    if not isinstance(delta, dict):
        return False, "missing attacker_value_delta"
    if not isinstance(gates, dict):
        return False, "missing live_balance_hard_gates"
    false_gates = [key for key, value in gates.items() if value is not True]
    if false_gates:
        return False, "live_balance_hard_gates not all true: " + ", ".join(false_gates)

    proof_hard_gates = candidate.get("hard_gates") if isinstance(candidate.get("hard_gates"), dict) else {}
    rejection_gates = candidate.get("rejection_gates") if isinstance(candidate.get("rejection_gates"), dict) else {}
    privilege_gate_values = []
    if "not_admin_governance_or_key_compromise" in proof_hard_gates:
        privilege_gate_values.append(proof_hard_gates.get("not_admin_governance_or_key_compromise"))
    if "not_admin_or_governance" in rejection_gates:
        privilege_gate_values.append(rejection_gates.get("not_admin_or_governance"))
    if not privilege_gate_values:
        return False, "missing admin/governance privilege rejection gate"
    if not all(value is True for value in privilege_gate_values):
        return False, "admin/governance/key-compromise extraction paths must be rejected"

    if not _as_positive_int(exploited.get("current_balance_raw")):
        return False, "current_balance_raw must be positive"
    if exploited.get("current_block_number") != context.get("block_number"):
        return False, "candidate block number does not match live context"
    if exploited.get("current_block_hash") != context.get("block_hash"):
        return False, "candidate block hash does not match live context"
    ledger_type = exploited.get("ledger_type")
    if ledger_type not in ("live_asset_ledger", "reward_liability_ledger"):
        return False, "ledger_type must be live_asset_ledger or reward_liability_ledger"
    ledger = context.get(ledger_type)
    if not isinstance(ledger, list):
        return False, f"{ledger_type} missing from live context"
    try:
        ledger_index = int(exploited.get("ledger_index"))
        row = ledger[ledger_index]
    except (TypeError, ValueError, IndexError):
        return False, "ledger_index does not point to a live context row"
    if _norm(exploited.get("asset_address")) != _norm(row.get("asset_address")):
        return False, "asset_address does not match ledger row"
    if _norm(exploited.get("holder_contract")) != _norm(row.get("holder_contract")):
        return False, "holder_contract does not match ledger row"
    if str(exploited.get("current_balance_raw")) != str(row.get("raw_balance") or row.get("backing_balance_raw")):
        return False, "current_balance_raw does not match ledger row"
    if delta.get("delta_is_positive") is not True or not _as_positive_int(delta.get("delta_raw")):
        return False, "attacker delta must be positive"
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate or build a BridgeIndex UPV2 live context.")
    parser.add_argument("--context", default="setup/live_context_v2.json")
    parser.add_argument("--from-acte", help="Optional ACTE/BridgeIndex live_context.json to convert first.")
    parser.add_argument("--out", default="setup/live_context_v2.json")
    parser.add_argument("--compat-out", default="setup/live_context.json")
    parser.add_argument("--validation-out", default="")
    args = parser.parse_args()

    if args.from_acte:
        source = _load_json(Path(args.from_acte))
        context = build_bridgeindex_upv2_context(source)
        validate_live_context(context)
        for output in (Path(args.out), Path(args.compat_out)):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
        print(f"wrote valid UPV2 live context to {args.out} and {args.compat_out}")
        return 0

    load_and_validate(args.context)
    if args.validation_out:
        write_validation_report(args.context, args.validation_out)
        print(f"wrote UPV2 live context validation report: {args.validation_out}")
    print(f"valid UPV2 live context: {args.context}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
