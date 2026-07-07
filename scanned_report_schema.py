"""JSON contract for reports placed in or produced from the scanner flow."""

from __future__ import annotations

import json
from typing import Any, Dict


LIVE_VALUE_BINDING: Dict[str, Any] = {
    "ledger_type": "live_asset_ledger | reward_liability_ledger",
    "ledger_index": 0,
    "asset_address": "",
    "asset_symbol": "",
    "holder_contract": "",
    "holder_role": "",
    "current_balance_raw": "0",
    "current_balance_source": "",
    "current_block_number": 0,
    "current_block_hash": "",
    "json_source_path": "",
}

ATTACKER_VALUE_DELTA: Dict[str, Any] = {
    "asset_address": "",
    "before_raw": "0",
    "after_raw": "0",
    "delta_raw": "0",
    "delta_is_positive": False,
    "why_beyond_entitlement": "",
}

LIVE_BALANCE_HARD_GATES: Dict[str, Any] = {
    "asset_currently_present": False,
    "asset_balance_nonzero": False,
    "asset_source_matches_live_context": False,
    "live_context_fresh": False,
    "attacker_can_trigger_now": False,
    "extraction_path_targets_that_asset": False,
    "not_future_deposit_dependent": False,
    "not_unbacked_reward_dependent": False,
}


SCANNED_REPORT_CONTRACT: Dict[str, Any] = {
    "schema_version": "scanned-report-v2",
    "verdict": "REJECT | NEEDS_LOCAL_PROOF | HIGH_CONFIDENCE_CANDIDATE",
    "reject_if_not_paid_scope": True,
    "paid_scope_match": "fund_extraction | protocol_value_drain | reward_extraction | unfair_reward_access | none",
    "report_identity": {
        "title": "",
        "source_report_id": "",
        "source_url": "",
        "source_severity": "critical | high | unknown",
        "external_root_primitive": (
            "authorization_bypass | accounting_drift | state_transition_ordering | "
            "reward_accumulator_error | oracle_price_manipulation | rounding_precision | "
            "replay_nonce | reentrancy_callback | token_transfer_semantics | invariant_mismatch"
        ),
    },
    "target_protocol_gate": {
        "blueprint_protocol": "",
        "live_context_protocol": "",
        "live_context_source": "setup/live_context.json | inline | none",
        "context_matches_blueprint": False,
        "context_mismatch_reason": "",
    },
    "live_onchain_context": {
        "chain": "",
        "chain_id": "",
        "latest_block": "",
        "captured_at_utc": "",
        "commands_used": [
            {
                "purpose": "",
                "command": "",
                "expected_output_field": "",
                "observed_value": "",
            }
        ],
        "contracts": [
            {
                "name": "",
                "address": "",
                "source_file": "",
                "proxy": {
                    "is_proxy": False,
                    "implementation": "",
                    "admin": "",
                },
                "balances": {
                    "native": {"raw": "", "human": "", "usd": "unknown"},
                    "erc20": [],
                    "erc721": [],
                    "erc1155": [],
                },
                "critical_views": {},
                "critical_mappings_or_structs": {},
                "events_or_recent_activity": {},
                "dependencies": [],
            }
        ],
        "protocol_preconditions": [
            {
                "name": "",
                "required_for_exploit": True,
                "live_value": "",
                "why_it_matters": "",
            }
        ],
    },
    "exploited_live_value": LIVE_VALUE_BINDING,
    "attacker_value_delta": ATTACKER_VALUE_DELTA,
    "live_balance_hard_gates": LIVE_BALANCE_HARD_GATES,
    "candidate": {
        "claim": "",
        "exact_code_path": [
            {
                "file": "",
                "function": "",
                "symbols_or_lines": "",
            }
        ],
        "attacker_path": {
            "attacker_profile": "",
            "preconditions": [],
            "attacker_controlled_inputs": [],
            "call_sequence": [],
        },
        "value_extraction_model": {
            "asset_or_reward": "",
            "who_loses_value": "",
            "how_attacker_gains_value": "",
            "why_this_is_not_only_dos_or_griefing": "",
        },
        "existing_checks_reviewed": [],
        "why_checks_fail": "",
        "local_proof_required": {
            "test_type": "",
            "test_file_to_add": "",
            "setup": [],
            "expected_assertion": "",
            "failure_condition": "",
        },
    },
    "rejection_gates": {
        "unprivileged_trigger": False,
        "concrete_attacker_value_gain": False,
        "not_admin_or_governance": False,
        "not_pure_external_dependency": False,
        "not_expected_behavior": False,
        "not_duplicate_or_known_issue": False,
        "not_stale_live_context": False,
    },
    "rejection_reason": "",
}


def scanned_report_contract_json() -> str:
    return json.dumps(SCANNED_REPORT_CONTRACT, indent=2)
