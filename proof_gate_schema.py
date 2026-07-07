"""JSON contract for the DeepWiki proof-gate judge pass."""

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


PROOF_GATE_CONTRACT: Dict[str, Any] = {
    "schema_version": "proof-gate-v2",
    "verdict": "REJECT | NEEDS_LOCAL_PROOF | HIGH_CONFIDENCE_CANDIDATE",
    "gate_question": (
        "Does this exact current protocol, with current live state, allow an "
        "unprivileged attacker to extract funds or rewards beyond entitlement?"
    ),
    "paid_scope_match": "fund_extraction | protocol_value_drain | reward_extraction | unfair_reward_access | none",
    "active_protocol": {
        "blueprint_project": "",
        "source_repo": "",
        "live_context_protocol": "",
        "context_matches_blueprint": False,
        "context_source": "setup/live_context.json | inline | none",
    },
    "candidate": {
        "source_file": "",
        "title_or_claim": "",
        "claimed_root_cause": "",
        "claimed_impact": "",
    },
    "hard_gates": {
        "current_protocol_only": False,
        "live_state_supports_preconditions": False,
        "unprivileged_attacker": False,
        "attacker_controls_trigger": False,
        "exact_code_path_exists": False,
        "concrete_fund_or_reward_gain": False,
        "gain_is_beyond_entitlement": False,
        "not_dos_grief_or_liveness_only": False,
        "not_admin_governance_or_key_compromise": False,
        "not_external_dependency_only": False,
        "not_expected_behavior": False,
        "not_known_duplicate": False,
    },
    "live_preconditions": [
        {
            "name": "",
            "required": True,
            "observed_value": "",
            "source": "live_context field | command | missing",
            "command_if_missing": "",
        }
    ],
    "source_code_basis": [
        {
            "file": "",
            "function": "",
            "symbols_or_lines": "",
            "why_it_matters": "",
        }
    ],
    "attacker_path": {
        "actor": "",
        "attacker_inputs": [],
        "call_sequence": [],
        "state_before": [],
        "state_after": [],
    },
    "extraction_analysis": {
        "asset_or_reward": "",
        "attacker_gain": "",
        "victim_or_protocol_loss": "",
        "why_gain_exceeds_entitlement": "",
    },
    "exploited_live_value": LIVE_VALUE_BINDING,
    "attacker_value_delta": ATTACKER_VALUE_DELTA,
    "live_balance_hard_gates": LIVE_BALANCE_HARD_GATES,
    "local_proof_required": {
        "test_type": "unit | fork | invariant | fuzz | manual",
        "test_file_to_add": "",
        "setup": [],
        "transaction_sequence": [],
        "expected_assertions": [],
        "reject_if_assertion_fails": "",
    },
    "rejection_reason": "",
}


def proof_gate_contract_json() -> str:
    return json.dumps(PROOF_GATE_CONTRACT, indent=2)
