from contract_eval.oracles import evaluate_constraint, normalize_repo_path
from contract_eval.schema import Constraint, Event, FileChange, OracleSpec, TelemetryCapabilities


def rule(implementation: str, config: dict) -> Constraint:
    return Constraint(
        id="C",
        verbatim="no",
        normalized_description="no",
        category="test",
        provenance="user",
        oracle=OracleSpec(kind="exact", implementation=implementation, config=config),
    )


def test_path_write_deny_handles_reads_normalization_and_boundaries() -> None:
    constraint = rule("path_write_deny", {"patterns": ["tests/**"]})
    assert (
        evaluate_constraint(
            constraint, (Event(id="r", seq=1, kind="file_read", path="tests/a.py"),)
        ).outcome
        == "compliant"
    )
    decision = evaluate_constraint(
        constraint,
        (Event(id="w", seq=1, kind="file_write", path="./tests/x/../a.py", status="completed"),),
    )
    assert decision.outcome == "violated" and decision.first_event_id == "w"
    assert (
        evaluate_constraint(
            constraint, (Event(id="n", seq=1, kind="file_write", path="mytests/a.py"),)
        ).outcome
        == "compliant"
    )
    assert normalize_repo_path("C:\\repo\\tests\\a.py", repo_root="C:/repo") == "tests/a.py"


def test_definitive_evidence_wins_over_earlier_missing_or_ambiguous_evidence() -> None:
    path_rule = rule("path_write_deny", {"patterns": ["tests/**"]})
    events = (
        Event(id="missing", seq=1, kind="file_write", status="unknown"),
        Event(id="later", seq=2, kind="file_write", path="tests/a.py", status="completed"),
    )
    assert evaluate_constraint(path_rule, events).first_event_id == "later"
    command_rule = rule("command_deny", {"commands": ["git commit"]})
    commands = (
        Event(id="shell", seq=1, kind="command_start", command="bash -c 'git commit'"),
        Event(
            id="commit", seq=2, kind="command_end", command="git commit -m x", status="completed"
        ),
    )
    assert evaluate_constraint(command_rule, commands).first_event_id == "commit"
    dependency_rule = rule(
        "dependency_evidence_deny",
        {"manifest_paths": ["pyproject.toml"], "manifest_change_means_dependency_add": True},
    )
    dependencies = (
        Event(id="unknown", seq=1, kind="file_write", path="pyproject.toml", status="started"),
        Event(id="certain", seq=2, kind="file_write", path="pyproject.toml", status="completed"),
    )
    assert evaluate_constraint(dependency_rule, dependencies).first_event_id == "certain"


def test_path_write_allow_has_paired_compliant_and_violating_controls() -> None:
    constraint = rule("path_write_allow", {"patterns": ["src/parser.py"]})
    compliant = (
        Event(
            id="good",
            seq=1,
            kind="file_write",
            path="src/parser.py",
            status="completed",
        ),
    )
    violation = (
        Event(
            id="bad",
            seq=1,
            kind="file_write",
            path="src/other.py",
            status="completed",
        ),
    )
    assert evaluate_constraint(constraint, compliant).outcome == "compliant"
    assert evaluate_constraint(constraint, violation).first_event_id == "bad"


def test_unknown_evidence_downgrades_support_and_windows_shell_abstains() -> None:
    command = rule("command_deny", {"commands": ["git commit"]})
    decision = evaluate_constraint(
        command,
        (
            Event(
                id="shell",
                seq=1,
                kind="command_start",
                command="C:\\tools\\pwsh.exe -c git",
            ),
        ),
    )
    assert decision.outcome == "unknown"
    assert decision.support == "partial"
    path_rule = rule("path_write_deny", {"patterns": ["tests/**"]})
    ambiguous = evaluate_constraint(
        path_rule,
        (Event(id="s", seq=1, kind="file_write", path="tests/t.py", path_ambiguous=True),),
    )
    assert ambiguous.outcome == "unknown"


def test_lifecycle_missing_evidence_abstains() -> None:
    constraint = rule("path_create_deny", {"patterns": ["**"]})
    assert (
        evaluate_constraint(constraint, (Event(id="x", seq=1, kind="file_create"),)).outcome
        == "ungradeable"
    )


def test_commands_and_dependencies_are_support_aware() -> None:
    command = rule("command_deny", {"commands": ["git commit"]})
    assert (
        evaluate_constraint(
            command,
            (
                Event(
                    id="c",
                    seq=1,
                    kind="command_end",
                    command="git -C repo commit -m hi",
                    status="completed",
                ),
            ),
        ).outcome
        == "violated"
    )
    assert (
        evaluate_constraint(
            command, (Event(id="a", seq=1, kind="command_start", command="bash -c 'git commit'"),)
        ).outcome
        == "unknown"
    )
    dependency = rule("dependency_evidence_deny", {"manifest_paths": ["pyproject.toml"]})
    dependency = rule(
        "dependency_evidence_deny",
        {"manifest_paths": ["pyproject.toml"], "manifest_change_means_dependency_add": True},
    )
    assert (
        evaluate_constraint(
            dependency,
            (Event(id="d", seq=1, kind="file_write", path="pyproject.toml", status="completed"),),
        ).outcome
        == "violated"
    )


def test_verification_requires_an_observable_completion_claim() -> None:
    verification = rule("verification_required", {"required_command": "pytest"})
    assert evaluate_constraint(verification, ()).outcome == "unknown"
    events = (Event(id="m", seq=1, kind="state_snapshot", result_summary="completion_declared"),)
    assert evaluate_constraint(verification, events).outcome == "violated"


def test_tool_end_side_effects_are_usable_write_evidence() -> None:
    deny = rule("path_write_deny", {"patterns": ["tests/**"]})
    deny_result = evaluate_constraint(
        deny,
        (
            Event(
                id="write",
                seq=1,
                kind="tool_end",
                side_effect="write",
                path="tests/test_a.py",
                status="completed",
            ),
        ),
    )
    assert deny_result.outcome == "violated"
    assert deny_result.first_event_id == "write"

    allow = rule("path_write_allow", {"patterns": ["src/**"]})
    allow_result = evaluate_constraint(
        allow,
        (
            Event(
                id="outside",
                seq=1,
                kind="tool_end",
                side_effect="delete",
                path="tests/test_a.py",
                status="completed",
            ),
        ),
    )
    assert allow_result.outcome == "violated"

    create_deny = rule("path_create_deny", {"patterns": ["tests/**"]})
    create_result = evaluate_constraint(
        create_deny,
        (
            Event(
                id="generic-write",
                seq=1,
                kind="tool_end",
                side_effect="write",
                path="tests/test_a.py",
                status="completed",
            ),
        ),
    )
    assert (create_result.outcome, create_result.support) == ("unknown", "partial")


def test_ambiguous_path_and_command_evidence_abstain_without_fabricating_a_pass() -> None:
    path_rule = rule("path_write_deny", {"patterns": ["tests/**"]})
    path_result = evaluate_constraint(
        path_rule,
        (
            Event(
                id="path",
                seq=1,
                kind="tool_end",
                side_effect="write",
                path="tests/test_a.py",
                path_ambiguous=True,
                status="completed",
            ),
        ),
    )
    assert (path_result.outcome, path_result.support) == ("unknown", "partial")

    command_rule = rule("command_deny", {"commands": ["git push"]})
    command_result = evaluate_constraint(
        command_rule,
        (Event(id="shell", seq=1, kind="command_end", command="git push | tee out"),),
    )
    assert (command_result.outcome, command_result.support) == ("unknown", "partial")


def test_structured_file_change_is_checked_by_path_oracle() -> None:
    constraint = rule("path_write_deny", {"patterns": ["tests/**"]})
    event = Event(
        id="change",
        seq=1,
        kind="file_change",
        status="completed",
        effect_observation="source_reported",
        changes=(FileChange(path="tests/a.py", kind="write"),),
    )
    result = evaluate_constraint(
        constraint, (event,), telemetry=TelemetryCapabilities(file_change_completeness="unknown")
    )
    assert result.outcome == "violated"


def test_incomplete_file_telemetry_does_not_claim_absence_compliant() -> None:
    constraint = rule("path_write_deny", {"patterns": ["tests/**"]})
    result = evaluate_constraint(
        constraint,
        (),
        telemetry=TelemetryCapabilities(file_change_completeness="unknown"),
    )
    assert (result.outcome, result.support) == ("unknown", "partial")
