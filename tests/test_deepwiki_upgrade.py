import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

import questions
import run_questions_generator_report
import run_automation_report
import workflow_chain
from bot_blueprint import load_blueprint
from bot_runtime import batch_limit, smoke_enabled, smoke_limit
from deepwiki_triage import classify_deepwiki_response, parse_json_response, save_deepwiki_response
from live_context_scanner import CHAIN_CONFIGS, COMMON_TOKENS, EXPLORER_TO_CHAIN
from live_context_schema import load_and_validate
from proof_gate_schema import PROOF_GATE_CONTRACT
from questions_generator import GetQuestions
from run_materialize_live_asset_seeds import materialize_live_asset_seeds
from scanned_report_schema import SCANNED_REPORT_CONTRACT


class BlueprintPromptTests(unittest.TestCase):
    def test_default_blueprint_points_to_bridgeindex(self):
        blueprint = load_blueprint()

        self.assertEqual(blueprint["repo_name"], "BridgeIndex")
        self.assertEqual(blueprint["source_repo"], "incjanta/BridgeIndex")
        self.assertIn("src/contracts/BotBridge.sol", blueprint["scope_files"])
        self.assertIn("src/contracts/Vote.sol", blueprint["scope_files"])
        self.assertIn("src/contracts/interface/IVote.sol", blueprint["scope_files"])
        self.assertIn("src/contracts/interface/IVote.sol", blueprint["context_interfaces"])
        self.assertEqual(len(blueprint["target_scopes"]), 2)
        self.assertTrue(any("fund extraction" in scope.lower() for scope in blueprint["target_scopes"]))
        self.assertTrue(any("reward extraction" in scope.lower() for scope in blueprint["target_scopes"]))
        self.assertTrue(blueprint["live_balance_policy"]["require_current_nonzero_balance"])

    def test_audit_prompt_uses_triage_verdicts_not_final_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            live_context = Path(tmp) / "live_context.json"
            live_context.write_text('{"target": {"label": "BridgeIndex"}, "chain": "bsc"}', encoding="utf-8")

            with patch.dict(os.environ, {"LIVE_CONTEXT_PATH": str(live_context)}, clear=False):
                prompt = questions.audit_format(
                    "[File: src/contracts/BotBridge.sol] [Function: deposit] Can an attacker over-withdraw?"
                )

        self.assertIn("## DeepWiki Automation Boundary", prompt)
        self.assertIn("## Live Context Snapshot", prompt)
        self.assertIn('"target": {"label": "BridgeIndex"}', prompt)
        self.assertIn("UPV2 Live Ledger Hard Rule", prompt)
        self.assertIn("REJECT", prompt)
        self.assertIn("NEEDS_LOCAL_PROOF", prompt)
        self.assertIn("HIGH_CONFIDENCE_CANDIDATE", prompt)
        self.assertIn("## Local Proof Required", prompt)
        self.assertNotIn("Audit Report\n\n## Title", prompt)

    def test_question_generator_includes_blueprint_and_local_proof_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            live_context = Path(tmp) / "live_context.json"
            live_context.write_text('{"target": {"label": "BridgeIndex"}, "latest_block": 108581678}', encoding="utf-8")

            with patch.dict(os.environ, {"LIVE_CONTEXT_PATH": str(live_context)}, clear=False):
                prompt = questions.question_generator(
                    "'File Name: src/contracts/BotBridge.sol -> Scope: Critical Fund extraction or protocol value drain'"
                )

        self.assertIn("DeepWiki Memory Blueprint", prompt)
        self.assertIn("## Live Context Snapshot", prompt)
        self.assertIn("Known rejection memory", prompt)
        self.assertIn("Local proof idea", prompt)
        self.assertIn("src/contracts/interface/IBotBridge.sol", prompt)
        self.assertIn("src/contracts/interface/IVote.sol", prompt)
        self.assertIn("108581678", prompt)

    def test_repository_rotation_ignores_stale_other_protocol_urls(self):
        repo_data = """
[
  "https://deepwiki.com/example/midnight--001",
  "https://deepwiki.com/example/623_sable_active_pool--001",
  "https://deepwiki.com/example/BridgeIndex--001",
  "https://deepwiki.com/example/BridgeIndex--002"
]
"""
        with patch("questions.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=repo_data)):
                urls = questions.load_repository_urls()

        self.assertEqual(
            urls,
            [
                "https://deepwiki.com/example/BridgeIndex--001",
                "https://deepwiki.com/example/BridgeIndex--002",
            ],
        )

    def test_scanner_prompt_expands_external_reports_into_scenarios(self):
        prompt = questions.scan_format("External high severity reward-accumulator report")

        self.assertIn("Scanner Intelligence Rules", prompt)
        self.assertIn("fund extraction / protocol value drain", prompt)
        self.assertIn("reward extraction / unfair reward access", prompt)
        self.assertIn("Do not stop after the first weak mapping", prompt)

    def test_scanner_prompt_requires_json_and_live_context_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            live_context = Path(tmp) / "live_context.json"
            live_context.write_text('{"target": {"label": "BridgeIndex"}, "chain": "bsc"}', encoding="utf-8")

            with patch.dict(os.environ, {"LIVE_CONTEXT_PATH": str(live_context)}, clear=False):
                prompt = questions.scan_format("External critical accounting report")

        self.assertIn("Scanned Report JSON Contract", prompt)
        self.assertIn("## Live Context Snapshot", prompt)
        self.assertIn('"schema_version": "scanned-report-v2"', prompt)
        self.assertIn("Output only valid JSON", prompt)
        self.assertIn("stale live context does not match active blueprint", prompt)
        self.assertIn("python3 live_context_scanner.py --from-questions", prompt)
        self.assertIn("ledger_index", prompt)

    def test_scan_format_treats_live_asset_seed_as_exact_ledger_scan(self):
        seed = {
            "schema_version": "upv2-live-asset-scan-seed-v1",
            "seed_type": "live_asset_ledger",
            "ledger_index": 0,
            "ledger_row": {
                "asset_address": "native",
                "symbol": "BNB",
                "holder_contract": "0x3cd6fb6b0cddd3610f0f4769aa7bb686cd4a4b55",
                "raw_balance": "4702000000000000",
            },
            "required_non_reject_binding": {
                "ledger_type": "live_asset_ledger",
                "ledger_index": 0,
                "asset_address": "native",
                "holder_contract": "0x3cd6fb6b0cddd3610f0f4769aa7bb686cd4a4b55",
                "current_balance_raw": "4702000000000000",
            },
        }

        prompt = questions.scan_format(json.dumps(seed))

        self.assertIn("WORKFLOW 7 LIVE ASSET SEED SCAN", prompt)
        self.assertIn("This is not a past hack report", prompt)
        self.assertIn("Treat `ledger_row` and `required_non_reject_binding` as the anchor", prompt)
        self.assertIn("rejection_gates.not_admin_or_governance=true", prompt)

    def test_scan_format_treats_past_live_hack_seed_as_historical_pattern_scan(self):
        seed = {
            "schema_version": "upv2-past-live-hack-seed-v1",
            "seed_type": "past_live_hack",
            "incident": {
                "name": "example bridge replay exploit",
                "root_primitive": "replay_nonce",
                "loss_asset": "USDT",
            },
            "attacker_pattern": "reused source-chain message to execute payout twice",
        }

        prompt = questions.scan_format(json.dumps(seed))

        self.assertIn("WORKFLOW 7 PAST LIVE HACK SEED SCAN", prompt)
        self.assertIn("historical exploit primitive seed", prompt)
        self.assertIn("map that primitive to BridgeIndex", prompt)
        self.assertIn("not the historical protocol's balance", prompt)

    def test_validation_prompt_embeds_live_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            live_context = Path(tmp) / "live_context.json"
            live_context.write_text('{"target": {"label": "Portal"}, "chain_id": 56}', encoding="utf-8")

            with patch.dict(os.environ, {"LIVE_CONTEXT_PATH": str(live_context)}, clear=False):
                prompt = questions.validation_format("candidate drains BNB")

        self.assertIn("## Live Context Snapshot", prompt)
        self.assertIn('"chain_id": 56', prompt)

    def test_scanned_report_contract_only_allows_paid_scope_families(self):
        self.assertTrue(SCANNED_REPORT_CONTRACT["reject_if_not_paid_scope"])
        self.assertIn("fund_extraction", SCANNED_REPORT_CONTRACT["paid_scope_match"])
        self.assertIn("reward_extraction", SCANNED_REPORT_CONTRACT["paid_scope_match"])
        self.assertIn("live_onchain_context", SCANNED_REPORT_CONTRACT)
        self.assertIn("exploited_live_value", SCANNED_REPORT_CONTRACT)
        self.assertIn("live_balance_hard_gates", SCANNED_REPORT_CONTRACT)

    def test_proof_gate_prompt_asks_exact_live_state_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            live_context = Path(tmp) / "live_context.json"
            live_context.write_text('{"target": {"label": "BridgeIndex"}, "chain": "bsc"}', encoding="utf-8")

            with patch.dict(os.environ, {"LIVE_CONTEXT_PATH": str(live_context)}, clear=False):
                prompt = questions.proof_gate_format("candidate overclaims rewards")

        self.assertIn("DEEPWIKI EXACT PROOF GATE", prompt)
        self.assertIn("Does this exact current protocol, with current live state", prompt)
        self.assertIn('"schema_version": "proof-gate-v2"', prompt)
        self.assertIn("Output only valid JSON", prompt)
        self.assertIn('"target": {"label": "BridgeIndex"}', prompt)
        self.assertIn("exploited_live_value", prompt)
        self.assertIn("Reject any admin-only", prompt)

    def test_proof_gate_contract_tracks_hard_gates(self):
        hard_gates = PROOF_GATE_CONTRACT["hard_gates"]

        self.assertIn("concrete_fund_or_reward_gain", hard_gates)
        self.assertIn("gain_is_beyond_entitlement", hard_gates)
        self.assertIn("not_dos_grief_or_liveness_only", hard_gates)
        self.assertIn("local_proof_required", PROOF_GATE_CONTRACT)
        self.assertIn("exploited_live_value", PROOF_GATE_CONTRACT)
        self.assertIn("live_balance_hard_gates", PROOF_GATE_CONTRACT)

    def test_bsc_is_first_class_scanner_chain(self):
        self.assertIn("bsc", CHAIN_CONFIGS)
        self.assertEqual(CHAIN_CONFIGS["bsc"].chain_id, 56)
        self.assertEqual(CHAIN_CONFIGS["bsc"].native_symbol, "BNB")
        self.assertEqual(EXPLORER_TO_CHAIN["bscscan.com"], "bsc")
        self.assertTrue(any(token["symbol"] == "USDT" for token in COMMON_TOKENS["bsc"]))

    def test_bridgeindex_live_context_v2_validates(self):
        context = load_and_validate(Path(__file__).resolve().parent.parent / "setup" / "live_context_v2.json")
        self.assertEqual(context["blueprint"]["project_name"], "BridgeIndex")
        self.assertEqual(context["block_hash"], "0x122165d97b1c836f8a4a62c475b2c379cc8c57299f6f92926f00c54b1f8f3f25")
        balances = {row["asset_address"]: row["raw_balance"] for row in context["live_asset_ledger"]}
        self.assertEqual(balances["native"], "4702000000000000")
        self.assertEqual(
            balances["0x55d398326f99059ff775485246999027b3197955"],
            "271979242947058091847273",
        )


class DeepWikiTriageTests(unittest.TestCase):
    def test_workflow_3_parses_stored_response_without_browser(self):
        response = 'prefix "[File: src/A.sol] [Function: withdraw] Can accounting be bypassed?" suffix'
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"QUESTION_DIR": tmp}, clear=False):
                paths = GetQuestions.save_question_content(response, source="stored-test")

            self.assertEqual(len(paths), 1)
            self.assertEqual(
                json.loads(Path(paths[0]).read_text(encoding="utf-8")),
                ["[File: src/A.sol] [Function: withdraw] Can accounting be bypassed?"],
            )

    def test_workflow_3_pending_records_keep_response_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp)
            payload = [{"question": "scope", "url": "https://example.test", "response": "answer"}]
            (pending / "batch.json").write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict(os.environ, {"SCOPE_QUESTIONS_PENDING_DIR": str(pending)}, clear=False):
                self.assertEqual(run_questions_generator_report.get_scope_questions_pending(), payload)

    def test_workflow_5_pending_records_keep_response_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp)
            payload = [{"question": "audit", "url": "https://example.test", "response": "result"}]
            (pending / "batch.json").write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict(os.environ, {"AUTOMATION_PENDING_DIR": str(pending)}, clear=False):
                self.assertEqual(run_automation_report.get_automation_pending(), payload)

    def test_classifies_known_verdicts(self):
        self.assertEqual(classify_deepwiki_response("#NoVulnerability found"), "reject")
        self.assertEqual(
            classify_deepwiki_response("## Verdict\nNEEDS_LOCAL_PROOF\n\n## Local Proof Required"),
            "needs_local_proof",
        )
        self.assertEqual(
            classify_deepwiki_response("## Verdict\nHIGH_CONFIDENCE_CANDIDATE"),
            "high_confidence_candidate",
        )
        self.assertEqual(
            classify_deepwiki_response('{"verdict": "NEEDS_LOCAL_PROOF", "paid_scope_match": "fund_extraction"}'),
            "needs_local_proof",
        )
        self.assertEqual(classify_deepwiki_response("plausible but legacy text"), "unknown")

    def test_save_forces_markdown_candidates_to_live_gate_rejections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "DEEPWIKI_CANDIDATE_DIR": str(root / "deepwiki_candidates"),
                "NEEDS_LOCAL_PROOF_DIR": str(root / "needs_local_proof"),
                "REJECTED_BY_DEEPWIKI_DIR": str(root / "rejected_by_deepwiki"),
                "REJECTED_BY_LIVE_GATE_DIR": str(root / "rejected_by_live_gate"),
            }

            with patch.dict(os.environ, env, clear=False):
                path = save_deepwiki_response(
                    "## Verdict\nNEEDS_LOCAL_PROOF\n\n## Local Proof Required\nassert x",
                    "https://deepwiki.com/example/query",
                )

            self.assertIsNotNone(path)
            assert path is not None
            self.assertEqual(path.parent.name, "rejected_by_live_gate")
            content = path.read_text(encoding="utf-8")
            self.assertIn("deepwiki_source_url", content)
            self.assertIn("deepwiki_verdict: needs_local_proof", content)
            self.assertIn("live_gate_forced_reject: true", content)
            self.assertFalse((root / "validated").exists())

    def test_save_forces_json_without_live_binding_to_live_gate_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "NEEDS_LOCAL_PROOF_DIR": str(root / "needs_local_proof"),
                "REJECTED_BY_LIVE_GATE_DIR": str(root / "rejected_by_live_gate"),
            }
            content = '{"verdict": "NEEDS_LOCAL_PROOF", "paid_scope_match": "reward_extraction"}'

            with patch.dict(os.environ, env, clear=False):
                path = save_deepwiki_response(content, "https://deepwiki.com/example/json", prefix="scan")

            self.assertIsNotNone(path)
            assert path is not None
            self.assertEqual(path.parent.name, "rejected_by_live_gate")
            self.assertEqual(path.suffix, ".json")
            parsed = parse_json_response(path.read_text(encoding="utf-8"))
            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed["deepwiki_verdict"], "needs_local_proof")
            self.assertEqual(parsed["deepwiki_source_url"], "https://deepwiki.com/example/json")
            self.assertTrue(parsed["live_gate_forced_reject"])

    def test_save_preserves_valid_live_bound_json_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {"NEEDS_LOCAL_PROOF_DIR": str(root / "needs_local_proof")}
            content = {
                "verdict": "NEEDS_LOCAL_PROOF",
                "paid_scope_match": "fund_extraction",
                "exploited_live_value": {
                    "ledger_type": "live_asset_ledger",
                    "ledger_index": 0,
                    "asset_address": "native",
                    "asset_symbol": "BNB",
                    "holder_contract": "0x3cd6fb6b0cddd3610f0f4769aa7bb686cd4a4b55",
                    "holder_role": "proxy",
                    "current_balance_raw": "4702000000000000",
                    "current_balance_source": "eth_getBalance",
                    "current_block_number": 108581678,
                    "current_block_hash": "0x122165d97b1c836f8a4a62c475b2c379cc8c57299f6f92926f00c54b1f8f3f25",
                    "json_source_path": "$.balances.native.raw",
                },
                "attacker_value_delta": {
                    "asset_address": "native",
                    "before_raw": "0",
                    "after_raw": "1",
                    "delta_raw": "1",
                    "delta_is_positive": True,
                    "why_beyond_entitlement": "test fixture",
                },
                "live_balance_hard_gates": {
                    "asset_currently_present": True,
                    "asset_balance_nonzero": True,
                    "asset_source_matches_live_context": True,
                    "live_context_fresh": True,
                    "attacker_can_trigger_now": True,
                    "extraction_path_targets_that_asset": True,
                    "not_future_deposit_dependent": True,
                    "not_unbacked_reward_dependent": True,
                },
                "rejection_gates": {
                    "not_admin_or_governance": True,
                },
            }

            with patch.dict(os.environ, env, clear=False):
                path = save_deepwiki_response(json.dumps(content), "https://deepwiki.com/example/json", prefix="scan")

            self.assertIsNotNone(path)
            assert path is not None
            self.assertEqual(path.parent.name, "needs_local_proof")

    def test_save_forces_admin_only_json_to_live_gate_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "NEEDS_LOCAL_PROOF_DIR": str(root / "needs_local_proof"),
                "REJECTED_BY_LIVE_GATE_DIR": str(root / "rejected_by_live_gate"),
            }
            content = {
                "verdict": "NEEDS_LOCAL_PROOF",
                "paid_scope_match": "fund_extraction",
                "exploited_live_value": {
                    "ledger_type": "live_asset_ledger",
                    "ledger_index": 0,
                    "asset_address": "native",
                    "asset_symbol": "BNB",
                    "holder_contract": "0x3cd6fb6b0cddd3610f0f4769aa7bb686cd4a4b55",
                    "holder_role": "proxy",
                    "current_balance_raw": "4702000000000000",
                    "current_balance_source": "eth_getBalance",
                    "current_block_number": 108581678,
                    "current_block_hash": "0x122165d97b1c836f8a4a62c475b2c379cc8c57299f6f92926f00c54b1f8f3f25",
                    "json_source_path": "$.balances.native.raw",
                },
                "attacker_value_delta": {
                    "asset_address": "native",
                    "before_raw": "0",
                    "after_raw": "1",
                    "delta_raw": "1",
                    "delta_is_positive": True,
                    "why_beyond_entitlement": "admin-only fixture",
                },
                "live_balance_hard_gates": {
                    "asset_currently_present": True,
                    "asset_balance_nonzero": True,
                    "asset_source_matches_live_context": True,
                    "live_context_fresh": True,
                    "attacker_can_trigger_now": True,
                    "extraction_path_targets_that_asset": True,
                    "not_future_deposit_dependent": True,
                    "not_unbacked_reward_dependent": True,
                },
                "rejection_gates": {
                    "not_admin_or_governance": False,
                },
            }

            with patch.dict(os.environ, env, clear=False):
                path = save_deepwiki_response(json.dumps(content), "https://deepwiki.com/example/admin", prefix="scan")

            self.assertIsNotNone(path)
            assert path is not None
            self.assertEqual(path.parent.name, "rejected_by_live_gate")
            parsed = parse_json_response(path.read_text(encoding="utf-8"))
            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertIn("admin/governance/key-compromise", parsed["live_gate_rejection_reason"])

    def test_rejects_are_not_saved_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"REJECTED_BY_DEEPWIKI_DIR": str(Path(tmp) / "rejected_by_deepwiki")}

            with patch.dict(os.environ, env, clear=False):
                path = save_deepwiki_response(
                    "## Verdict\nREJECT\n\n## Rejection Reason\nexpected behavior",
                    "https://deepwiki.com/example/reject",
                )

            self.assertIsNone(path)
            self.assertFalse((Path(tmp) / "rejected_by_deepwiki").exists())


class RuntimeLimitTests(unittest.TestCase):
    def test_smoke_limit_defaults_to_full_batch(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(smoke_limit())
            self.assertFalse(smoke_enabled())
            self.assertEqual(batch_limit(25), 25)

    def test_smoke_limit_overrides_batch_size(self):
        with patch.dict(os.environ, {"BOT_SMOKE_LIMIT": "2"}, clear=True):
            self.assertEqual(smoke_limit(), 2)
            self.assertTrue(smoke_enabled())
            self.assertEqual(batch_limit(25), 2)

    def test_smoke_limit_rejects_invalid_values(self):
        with patch.dict(os.environ, {"BOT_SMOKE_LIMIT": "0"}, clear=True):
            with self.assertRaises(ValueError):
                smoke_limit()


class WorkflowChainTests(unittest.TestCase):
    def test_stage_verifier_and_remaining_inputs_use_expected_globs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scope").mkdir()
            (root / "scope" / "one.json").write_text("[]", encoding="utf-8")

            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                self.assertTrue(workflow_chain.verify_stage("1"))
                self.assertTrue(workflow_chain.has_remaining("2"))
                self.assertFalse(workflow_chain.verify_stage("2"))
            finally:
                os.chdir(old_cwd)

    def test_stage_zero_two_accepts_live_asset_seed_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scanned").mkdir()
            (root / "scanned" / "live_asset_seed__bsc__holder__native_bnb.json").write_text("{}", encoding="utf-8")

            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                self.assertTrue(workflow_chain.verify_stage("0.2"))
            finally:
                os.chdir(old_cwd)

    def test_stage_seven_accepts_json_scanner_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scanned").mkdir()
            (root / "scanned" / "external-report.json").write_text("{}", encoding="utf-8")

            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                self.assertTrue(workflow_chain.has_remaining("7"))
            finally:
                os.chdir(old_cwd)


class DeploymentReadinessTests(unittest.TestCase):
    def test_internal_operator_docs_are_ignored(self):
        root = Path(__file__).resolve().parent.parent
        ignored_docs = {
            "UPV2Upgrade.md",
            "UPV2Upgrade_BridgeIndex_Addendum.md",
            "SCANNED_INPUT_CONTRACT.md",
            "DEEPWIKI_UPGRADE_PLAN.md",
            "check.md",
        }
        ignore_lines = {
            line.strip()
            for line in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }

        self.assertTrue(ignored_docs.issubset(ignore_lines))

    def test_workflow_commit_messages_include_deployment_token(self):
        root = Path(__file__).resolve().parent.parent
        token = "648guf5868gfj58685f"
        workflow_files = sorted((root / ".github" / "workflows").glob("*.yml"))
        self.assertGreaterEqual(len(workflow_files), 10)

        for workflow in workflow_files:
            content = workflow.read_text(encoding="utf-8")
            for line in content.splitlines():
                if "git commit -m" in line:
                    self.assertIn(token, line, workflow.name)

    def test_workflow_three_does_not_commit_move_only_pending_queue(self):
        root = Path(__file__).resolve().parent.parent
        workflow = root / ".github" / "workflows" / "3_run_question_generator_questions.yml"
        content = workflow.read_text(encoding="utf-8")

        move_step = content.index("python run_questions_generator_report_generate.py")
        report_step = content.index("python run_questions_generator_report.py")
        between_move_and_report = content[move_step:report_step]

        self.assertNotIn("git commit -m", between_move_and_report)
        self.assertIn("git diff --cached --quiet", content)
        self.assertIn("Verify and advance chain", content)
        self.assertNotIn("Trigger next batch after generate", content)

    def test_report_runner_restores_pending_file_when_generation_fails(self):
        class FailingQuestions:
            def __init__(self, teardown=False):
                pass

            def get_questions(self, url):
                raise RuntimeError("empty DeepWiki output")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending_dir = root / "scope_questions_pending"
            scope_questions_dir = root / "scope_questions"
            pending_dir.mkdir()
            source_file = pending_dir / "one.json"
            source_file.write_text(
                json.dumps(
                    [
                        {
                            "question": "Can value be extracted?",
                            "url": "https://deepwiki.com/example/repo",
                            "questions_generated": False,
                        }
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "SCOPE_QUESTIONS_PENDING_DIR": str(pending_dir),
                    "SCOPE_QUESTIONS_DIR": str(scope_questions_dir),
                    "QUESTION_DIR": str(root / "question"),
                },
                clear=False,
            ), patch.object(run_questions_generator_report, "GetQuestions", FailingQuestions):
                with self.assertRaisesRegex(RuntimeError, "empty DeepWiki output"):
                    run_questions_generator_report.main()

            restored_file = scope_questions_dir / "one.json"
            self.assertTrue(restored_file.exists())
            self.assertFalse(source_file.exists())
            restored_data = json.loads(restored_file.read_text(encoding="utf-8"))
            self.assertFalse(restored_data[0]["questions_generated"])

    def test_expected_github_actions_workflows_are_present(self):
        root = Path(__file__).resolve().parent.parent
        expected = {
            "0_refresh_live_context.yml",
            "0_1_validate_live_context.yml",
            "0_2_live_asset_seed.yml",
            "1_split_scope.yml",
            "2_run_question_generator.yml",
            "3_run_question_generator_questions.yml",
            "4_run_automation.yml",
            "5_run_report.yml",
            "6_run_validator.yml",
            "7_run_scanner.yml",
            "8_run_validator_report.yml",
            "9_run_clean_up.yml",
            "actions_index_refresh.yml",
            "setup.yml",
            "setup_index.yml",
        }
        workflow_names = {path.name for path in (root / ".github" / "workflows").glob("*.yml")}

        self.assertTrue(expected.issubset(workflow_names))


class LiveAssetSeedTests(unittest.TestCase):
    def test_materialize_live_asset_seeds_writes_workflow_seven_inputs(self):
        context_path = Path(__file__).resolve().parent.parent / "setup" / "live_context_v2.json"
        with tempfile.TemporaryDirectory() as tmp:
            written = materialize_live_asset_seeds(context_path=str(context_path), out_dir=str(Path(tmp) / "scanned"))

            self.assertGreaterEqual(len(written), 2)
            payload = json.loads(written[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "upv2-live-asset-scan-seed-v1")
            self.assertEqual(payload["seed_type"], "live_asset_ledger")
            self.assertIn("Reject admin-only", payload["scanner_instruction"])

    def test_stage_six_uses_staged_candidate_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "needs_local_proof").mkdir()
            (root / "needs_local_proof" / "candidate.json").write_text("{}", encoding="utf-8")

            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                self.assertTrue(workflow_chain.has_remaining("6"))
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
