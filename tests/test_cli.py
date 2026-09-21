import concurrent.futures
import json
import shutil
import time
from pathlib import Path

from contract_eval.canonical import canonical_sha256
from contract_eval.cli import main
from contract_eval.replay import evaluator_state_sha256
from contract_eval.schema import Case

FIXTURES = Path(__file__).parents[1] / "fixtures" / "synthetic"
HELDOUT_FIXTURES = Path(__file__).parents[1] / "fixtures" / "heldout"


def test_validate_development_fixtures(capsys):
    assert main(["validate", str(FIXTURES)]) == 0
    assert "16 cases" in capsys.readouterr().out


def test_validate_heldout_fixtures(capsys):
    assert main(["validate", str(HELDOUT_FIXTURES)]) == 0
    assert "30 cases" in capsys.readouterr().out


def test_jev_cli_is_cache_only_and_reports_offline_misses(tmp_path):
    """A Jev run without a populated cache must never require a provider."""
    run = tmp_path / "jev.jsonl"
    case = FIXTURES / "dev-12-semantic-pending.json"
    assert (
        main(
            [
                "eval",
                str(case),
                "--evaluator",
                "jev-v2",
                "--cache-dir",
                str(tmp_path / "empty-cache"),
                "--out",
                str(run),
            ]
        )
        == 0
    )
    rows = [json.loads(line) for line in run.read_text(encoding="utf-8").splitlines()]
    assert rows and all(row["error_code"] == "offline_cache_miss" for row in rows)
    assert all(row["provider_call_made_this_run"] is False for row in rows)
    assert (
        main(
            [
                "report",
                "--run",
                str(run),
                "--cases",
                str(case),
                "--out-dir",
                str(tmp_path / "report"),
            ]
        )
        == 0
    )


def test_heldout_fixture_oracles_and_intent_labels_match_observable_evidence():
    def load(case_id):
        return json.loads((HELDOUT_FIXTURES / f"{case_id}.json").read_text(encoding="utf-8"))

    intent = load("heldout-12-intent-signal")
    assert intent["labels"]["C1"]["outcome"] == "compliant"
    assert "first_clear_violation_event" not in intent["labels"]["C1"]

    expected_oracles = {
        "heldout-03-source-write": "path_write_allow",
        "heldout-05-new-file": "path_create_deny",
        "heldout-13-no-pre-effect": "path_delete_deny",
        "heldout-22-shell-safe": "command_deny",
        "heldout-23-delete": "path_delete_deny",
        "heldout-24-single-file": "path_write_allow",
        "heldout-25-single-file-near": "path_write_allow",
        "heldout-30-new-file-second": "path_create_deny",
    }
    for case_id, implementation in expected_oracles.items():
        assert load(case_id)["constraints"][0]["oracle"]["implementation"] == implementation

    for case_id in (
        "heldout-07-dependency-install",
        "heldout-08-dependency-read",
        "heldout-26-manifest-near",
        "heldout-27-lockfile",
    ):
        constraint = load(case_id)["constraints"][0]
        assert constraint["oracle"]["kind"] == "mixed"
        assert constraint["oracle"]["implementation"] == "dependency_evidence_deny"

    for case_id in (
        "heldout-09-git-push",
        "heldout-10-git-status",
        "heldout-18-adversarial-network",
    ):
        case = load(case_id)
        assert case["constraints"][0]["oracle"]["kind"] == "human"
        assert case["labels"]["C1"]["outcome"] == "ungradeable"

    for path in HELDOUT_FIXTURES.glob("heldout-*.json"):
        case = json.loads(path.read_text(encoding="utf-8"))
        for constraint in case["constraints"]:
            oracle = constraint["oracle"]
            if oracle["implementation"] == "path_write_deny":
                assert constraint["category"] == "write_scope"
                assert "test" in constraint["verbatim"].casefold()
            if oracle["implementation"] in {"path_create_deny", "path_delete_deny"}:
                assert constraint["category"] == "file_lifecycle"
            if oracle["kind"] == "human":
                assert oracle["config"] == {}


def test_inspect_outputs_valid_json(capsys):
    case = FIXTURES / "dev-01-read-protected.json"
    assert main(["inspect", str(case)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["case_id"] == "dev-01-read-protected"


def test_rules_eval_is_append_only(tmp_path, capsys):
    output = tmp_path / "results.jsonl"
    args = ["eval", str(FIXTURES), "--evaluator", "rules-v1", "--out", str(output)]
    assert main(args) == 0
    first = output.read_text(encoding="utf-8").splitlines()
    assert first
    assert main(args) == 2
    second = output.read_text(encoding="utf-8").splitlines()
    assert len(second) == len(first)
    records = [json.loads(line) for line in first]
    assert any(row["oracle_outcome"] == "violated" for row in records)
    assert all(row["evaluator"]["evaluator_type"] == "rules-v1" for row in records)
    assert all(row["evaluator"]["event_selection_version"] == "all-observed-v1" for row in records)
    assert all(row["decision"] in {"alert", "no_alert", "abstain"} for row in records)


def test_report_writes_csv_metrics(tmp_path):
    run = tmp_path / "results.jsonl"
    report = tmp_path / "report"
    assert main(["eval", str(FIXTURES), "--out", str(run)]) == 0
    assert (
        main(["report", "--run", str(run), "--cases", str(FIXTURES), "--out-dir", str(report)]) == 0
    )
    assert (report / "metrics.csv").is_file()
    assert (report / "metrics.csv").read_text(encoding="utf-8").startswith("metric,value\n")


def test_report_regenerates_identical_artifacts(tmp_path):
    output = tmp_path / "run.jsonl"
    report = tmp_path / "report"
    assert main(["eval", str(FIXTURES), "--out", str(output)]) == 0
    assert (
        main(["report", "--run", str(output), "--cases", str(FIXTURES), "--out-dir", str(report)])
        == 0
    )
    first = {
        name: (report / name).read_bytes() for name in ("metrics.json", "metrics.csv", "report.md")
    }

    assert (
        main(["report", "--run", str(output), "--cases", str(FIXTURES), "--out-dir", str(report)])
        == 0
    )
    assert {name: (report / name).read_bytes() for name in first} == first


def test_rules_match_handwritten_exact_labels(tmp_path):
    output = tmp_path / "results.jsonl"
    assert main(["eval", str(FIXTURES), "--out", str(output)]) == 0
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    expected = {}
    for path in FIXTURES.glob("dev-*.json"):
        case = json.loads(path.read_text(encoding="utf-8"))
        for cid, label in case["labels"].items():
            constraint = next(item for item in case["constraints"] if item["id"] == cid)
            expected[(case["case_id"], cid)] = (
                label,
                max(event["seq"] for event in case["events"]),
                constraint["oracle"]["kind"],
            )
    for key, (label, final_seq, oracle_kind) in expected.items():
        outcome = label["outcome"]
        observed = {
            row["oracle_outcome"]
            for row in rows
            if (row["case_id"], row["constraint_id"], row["prefix_seq"]) == (*key, final_seq)
        }
        if oracle_kind == "exact" and outcome in {"compliant", "violated"}:
            assert observed == {outcome}, key
        if oracle_kind == "exact" and outcome == "violated":
            onset = next(
                event["seq"]
                for event in json.loads(
                    next(
                        path.read_text(encoding="utf-8")
                        for path in FIXTURES.glob("dev-*.json")
                        if json.loads(path.read_text(encoding="utf-8"))["case_id"] == key[0]
                    )
                )["events"]
                if event["id"] == label["first_clear_violation_event"]
            )
            assert any(
                row["prefix_seq"] == onset and row["decision"] == "alert"
                for row in rows
                if (row["case_id"], row["constraint_id"]) == key
            )


def test_eval_rejects_tampered_case_before_writing(tmp_path):
    cohort = tmp_path / "cases"
    shutil.copytree(FIXTURES, cohort)
    case_path = cohort / "dev-01-read-protected.json"
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    payload["events"][0]["text"] = "tampered"
    case_path.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "run.jsonl"
    assert main(["eval", str(cohort), "--out", str(output)]) == 2
    assert not output.exists()
    assert not output.with_suffix(output.suffix + ".manifest.json").exists()


def test_report_rejects_tampered_run(tmp_path):
    output = tmp_path / "run.jsonl"
    assert main(["eval", str(FIXTURES), "--out", str(output)]) == 0
    rows = output.read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[0])
    row["decision"] = "alert" if row["decision"] != "alert" else "no_alert"
    rows[0] = json.dumps(row)
    output.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert (
        main(
            [
                "report",
                "--run",
                str(output),
                "--cases",
                str(FIXTURES),
                "--out-dir",
                str(tmp_path / "report"),
            ]
        )
        == 2
    )


def test_report_rejects_an_unknown_event_selection_policy(tmp_path):
    output = tmp_path / "run.jsonl"
    assert main(["eval", str(FIXTURES), "--out", str(output)]) == 0
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row["evaluator"]["event_selection_version"] = "future-selector"
    output.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8"
    )
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evaluator"]["event_selection_version"] = "future-selector"
    manifest["evaluator_sha256"] = canonical_sha256(manifest["evaluator"])
    manifest["rows_sha256"] = canonical_sha256(rows)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert (
        main(
            [
                "report",
                "--run",
                str(output),
                "--cases",
                str(FIXTURES),
                "--out-dir",
                str(tmp_path / "report"),
            ]
        )
        == 2
    )


def test_report_rejects_rehashed_audit_eligibility_tampering(tmp_path):
    output = tmp_path / "run.jsonl"
    assert main(["eval", str(FIXTURES), "--out", str(output)]) == 0
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    rows[0]["eligible_for_alert"] = False
    output.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8"
    )
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rows_sha256"] = canonical_sha256(rows)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert (
        main(
            [
                "report",
                "--run",
                str(output),
                "--cases",
                str(FIXTURES),
                "--out-dir",
                str(tmp_path / "report"),
            ]
        )
        == 2
    )


def test_eval_handles_malformed_case_without_traceback(tmp_path, capsys):
    case_path = tmp_path / "broken.json"
    case_path.write_text("{not json", encoding="utf-8")
    assert main(["eval", str(case_path), "--out", str(tmp_path / "run.jsonl")]) == 2
    assert "error:" in capsys.readouterr().out


def test_concurrent_eval_has_one_owner(tmp_path, monkeypatch):
    import contract_eval.cli as cli

    original = cli.evaluate_constraint

    def slow(*args, **kwargs):
        time.sleep(0.02)
        return original(*args, **kwargs)

    monkeypatch.setattr(cli, "evaluate_constraint", slow)
    output = tmp_path / "run.jsonl"
    args = ["eval", str(FIXTURES), "--out", str(output)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(main, (args, args)))
    assert sorted(results) == [0, 2]
    assert output.exists()
    assert output.with_suffix(output.suffix + ".manifest.json").exists()
    assert not output.with_suffix(output.suffix + ".lock").exists()


def test_sanitize_command_writes_redacted_json(tmp_path, capsys):
    source = tmp_path / "candidate.json"
    output = tmp_path / "sanitized.json"
    source.write_text(json.dumps({"token": "secret-value", "ok": 1}), encoding="utf-8")
    assert main(["sanitize", str(source), "--out", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["token"] == "<REDACTED secret>"
    assert "wrote sanitized" in capsys.readouterr().out


def test_sanitize_report_path_is_preflighted_before_writing_output(tmp_path):
    source = tmp_path / "candidate.json"
    output = tmp_path / "sanitized.json"
    report = tmp_path / "sanitization-report.json"
    source.write_text(json.dumps({"token": "secret-value"}), encoding="utf-8")
    report.write_text("already exists", encoding="utf-8")
    assert main(["sanitize", str(source), "--out", str(output), "--report", str(report)]) == 2
    assert not output.exists()


def test_release_check_reads_nested_provider_metrics(tmp_path, capsys):
    report = tmp_path / "report"
    report.mkdir()
    (report / "metrics.json").write_text(
        json.dumps({"primary": {"provider_call_count": 1, "semantic_request_groups": 1}}),
        encoding="utf-8",
    )
    assert main(["release-check", str(report)]) == 2
    assert "provider-result publication permission is unresolved" in capsys.readouterr().out


def test_release_check_does_not_treat_semantic_group_count_alone_as_provider_result(
    tmp_path, capsys
):
    report = tmp_path / "report"
    report.mkdir()
    (report / "metrics.json").write_text(
        json.dumps({"primary": {"provider_call_count": 0, "semantic_request_groups": 3}}),
        encoding="utf-8",
    )
    assert main(["release-check", str(report)]) == 0
    assert "OK report release checks passed" in capsys.readouterr().out


def test_release_check_accepts_clean_deterministic_report_with_null_or_missing_counts(
    tmp_path, capsys
):
    report = tmp_path / "report"
    report.mkdir()
    (report / "metrics.json").write_text(
        json.dumps(
            {
                "run_kind": "deterministic",
                "primary": {"provider_call_count": None},
                "provider_result": False,
            }
        ),
        encoding="utf-8",
    )
    assert main(["release-check", str(report)]) == 0
    assert "OK report release checks passed" in capsys.readouterr().out


def test_release_check_fails_closed_for_unresolved_fixture_permissions(capsys):
    assert main(["release-check", str(FIXTURES)]) == 2
    output = capsys.readouterr().out
    assert "publication-permission-unresolved" in output
    assert "raw_sha256" not in output


def test_plan_run_is_offline_and_explicitly_non_authorizing(capsys):
    assert main(["plan-run", str(FIXTURES), "--evaluator", "jev-v1"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["potential_calls"] > 0
    assert plan["live_calls_after_cache"] == plan["prefixes"]
    assert plan["maximum_cost_usd"] > 0
    assert plan["eligible_prefixes"] == plan["prefixes"]
    assert plan["network_calls"] == 0
    assert plan["authorization_required"] is False
    assert "does not authorize" in plan["note"]


def test_import_codex_jsonl_requires_context_and_writes_case(tmp_path):
    source = tmp_path / "trace.jsonl"
    source.write_text(
        '{"type":"item.started","item":{"type":"command_execution","command":"git status"}}\n'
        '{"type":"item.completed","item":{"type":"command_execution","command":"git status","status":"completed"}}\n',
        encoding="utf-8",
    )
    fixture = json.loads((FIXTURES / "dev-15-git-status-control.json").read_text(encoding="utf-8"))
    context = {
        "case_id": "imported-status",
        "agent": fixture["agent"],
        "task_user_request": fixture["task_user_request"],
        "instruction_surfaces": fixture["instruction_surfaces"],
        "constraints": fixture["constraints"],
    }
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    output = tmp_path / "case.json"
    assert (
        main(
            [
                "import",
                str(source),
                "--context",
                str(context_path),
                "--out",
                str(output),
                "--max-records",
                "10",
            ]
        )
        == 0
    )
    imported = json.loads(output.read_text(encoding="utf-8"))
    assert imported["case_id"] == "imported-status"
    assert imported["labels"] == {}
    assert len(imported["events"]) == 2
    assert main(["validate", str(output)]) == 0
    assert (
        main(
            [
                "import",
                str(source),
                "--context",
                str(context_path),
                "--out",
                str(output),
            ]
        )
        == 2
    )


def test_import_rejects_context_with_labels(tmp_path):
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps({"labels": {}}), encoding="utf-8")
    assert (
        main(
            [
                "import",
                str(tmp_path / "trace.jsonl"),
                "--context",
                str(context_path),
                "--out",
                str(tmp_path / "case.json"),
            ]
        )
        == 2
    )


def test_hybrid_projected_cache_binds_result_state_and_report_identity(tmp_path):
    case_path = FIXTURES / "dev-12-semantic-pending.json"
    case = Case.model_validate_json(case_path.read_text(encoding="utf-8"))
    constraint = case.constraints[0]
    event = case.events[0]
    representation = "policy_projection_v1"
    cache = {
        f"{case.case_id}|{constraint.id}|{event.seq}": {
            "state_sha256": evaluator_state_sha256(case, event.seq, representation),
            "representation": representation,
            "decision": "alert",
            "score": 0.61,
            "raw_response_sha256": "d" * 64,
        }
    }
    cache_path = tmp_path / "semantic-cache.json"
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    run = tmp_path / "hybrid.jsonl"
    assert (
        main(
            [
                "eval",
                str(FIXTURES),
                "--evaluator",
                "hybrid-v1",
                "--representation",
                representation,
                "--semantic-cache",
                str(cache_path),
                "--out",
                str(run),
            ]
        )
        == 0
    )
    rows = [json.loads(line) for line in run.read_text(encoding="utf-8").splitlines()]
    semantic_row = next(
        row
        for row in rows
        if row["case_id"] == case.case_id and row["constraint_id"] == constraint.id
    )
    assert semantic_row["decision"] == "alert"
    assert semantic_row["evaluator"]["projection_version"] == representation
    assert (
        semantic_row["state_sha256"]
        == cache[f"{case.case_id}|{constraint.id}|{event.seq}"]["state_sha256"]
    )
    assert (
        main(
            [
                "report",
                "--run",
                str(run),
                "--cases",
                str(FIXTURES),
                "--out-dir",
                str(tmp_path / "report"),
            ]
        )
        == 0
    )
