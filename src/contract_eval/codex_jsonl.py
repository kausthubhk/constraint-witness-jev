"""Conservative offline adapter for ``codex exec --json`` JSONL traces."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Literal

from .canonical import canonical_sha256
from .evidence import normalized_case_evidence
from .ingest import DEFAULT_MAX_LINE_BYTES, DEFAULT_MAX_RECORDS, read_jsonl_bounded_with_sha256
from .schema import (
    AgentProvenance,
    Case,
    Constraint,
    Event,
    FileChange,
    InstructionSurface,
    SourceKind,
    SourceProvenance,
    TelemetryCapabilities,
)

NORMALIZER_VERSION = "codex-exec-jsonl-v2"
TRACE_FORMAT = "codex-exec-jsonl"
_MAX_TEXT = 16_384
_MAX_DIFF = 64_000
_MAX_CHANGES = 1_000
_MAX_ARGUMENT_BYTES = 32_768
_REDIRECT_RE = re.compile(r"(?:^|\s)(>>|>)(?:\s*)([^\s]+)(?:\s*$)")


@dataclass(frozen=True)
class CodexCaseContext:
    case_id: str
    agent: AgentProvenance
    task_user_request: str
    instruction_surfaces: tuple[InstructionSurface, ...]
    constraints: tuple[Constraint, ...]
    origin_uri: str | None = None
    license: str | None = None
    redistribution_allowed: bool | None = None
    starting_repo_tree: tuple[str, ...] = ()
    filesystem_case_sensitive: bool | None = None


def _bounded_text(value: object, limit: int = _MAX_TEXT) -> str | None:
    return value[:limit] if isinstance(value, str) else None


def _status(value: object) -> Literal["completed", "failed", "unknown"]:
    if value == "completed":
        return "completed"
    if value in {"failed", "declined", "cancelled", "canceled"}:
        return "failed"
    return "unknown"


def _json_safe(value: object, limit: int = _MAX_ARGUMENT_BYTES) -> object | None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > limit:
        return None
    return json.loads(encoded)


def _command_tokens(command: str) -> list[str] | None:
    if any(op in command for op in ("|", ";", "&&", "||", "$(", "`", "\n", "\r")):
        return None
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    if not tokens:
        return None
    executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")
    if executable in {"sh", "bash", "zsh", "cmd", "powershell", "pwsh", "env"}:
        return None
    if any("$" in token or "*" in token or "?" in token for token in tokens):
        return None
    return tokens


def _command_effect(command: str) -> tuple[str, str | None, bool] | None:
    tokens = _command_tokens(command)
    if tokens is None:
        name = command.strip().split(maxsplit=1)[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        if name in {"rm", "touch", "cp", "mv", "mkdir", "tee", "sed", "echo", "cat"}:
            return ("delete" if name == "rm" else "write", None, True)
        return None
    name = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")
    if name in {"rm", "touch", "mkdir"}:
        operands = [x for x in tokens[1:] if not x.startswith("-")]
        return (
            (("delete" if name == "rm" else "write"), operands[0], False)
            if len(operands) == 1
            else (("delete" if name == "rm" else "write"), None, True)
        )
    if name in {"cp", "mv"}:
        operands = [x for x in tokens[1:] if not x.startswith("-")]
        return ("write", operands[1], False) if len(operands) == 2 else ("write", None, True)
    if name == "tee":
        operands = [x for x in tokens[1:] if not x.startswith("-")]
        return (
            ("write", operands[0], False)
            if len(operands) == 1 and tokens[1] == operands[0]
            else ("write", None, True)
        )
    if name in {"echo", "cat"}:
        match = _REDIRECT_RE.search(command)
        if match:
            target = match.group(2).strip("'\"")
            return (
                ("write", target, False)
                if target and not any(x in target for x in ("$", "*", "?"))
                else ("write", None, True)
            )
    if name == "sed" and any(token == "-i" or token.startswith("-i") for token in tokens[1:]):
        operands = [x for x in tokens[1:] if not x.startswith("-")]
        return ("write", operands[-1], False) if len(operands) >= 2 else ("write", None, True)
    return None


def _file_changes(item: dict[str, Any]) -> tuple[FileChange, ...]:
    raw_changes = item.get("changes")
    if raw_changes is None and "path" in item:
        raw_changes = [
            {"path": item.get("path"), "kind": item.get("kind", item.get("change_kind"))}
        ]
    if not isinstance(raw_changes, list):
        return ()
    result: list[FileChange] = []
    for raw in raw_changes[:_MAX_CHANGES]:
        if not isinstance(raw, dict):
            result.append(FileChange(path_ambiguous=True))
            continue
        raw_kind = raw.get("kind", raw.get("change_kind"))
        kind: Literal["create", "write", "delete", "unknown"] = "unknown"
        if raw_kind in {"create", "created", "add", "added"}:
            kind = "create"
        elif raw_kind in {"write", "update", "updated", "modify", "modified"}:
            kind = "write"
        elif raw_kind in {"delete", "deleted", "remove", "removed"}:
            kind = "delete"
        path = raw.get("path") if isinstance(raw.get("path"), str) else None
        result.append(
            FileChange(
                path=path,
                kind=kind,
                diff=_bounded_text(raw.get("diff"), _MAX_DIFF),
                path_ambiguous=path is None or any(x in path for x in ("$", "*", "?")),
            )
        )
    return tuple(result)


def _event_from_record(record: Any, seq: int) -> Event | None:
    value = record.value
    envelope_type = value.get("type")
    raw_ref = f"{TRACE_FORMAT}:line:{record.line_number}"
    if envelope_type == "error":
        return Event(
            id=f"e{seq}",
            seq=seq,
            kind="error",
            actor="environment",
            status="failed",
            text=_bounded_text(value.get("message")),
            raw_ref=raw_ref,
        )
    item = value.get("item")
    if not isinstance(item, dict):
        return (
            None
            if envelope_type
            in {
                "thread.started",
                "thread.completed",
                "turn.started",
                "turn.completed",
                "turn.failed",
            }
            else Event(id=f"e{seq}", seq=seq, kind="unknown", raw_ref=raw_ref)
        )
    item_type = item.get("type")
    status = _status(item.get("status"))
    started = envelope_type == "item.started"
    completed = envelope_type == "item.completed"
    if item_type == "command_execution" and (started or completed):
        command = item.get("command") if isinstance(item.get("command"), str) else None
        effect = (
            _command_effect(command) if completed and status == "completed" and command else None
        )
        kwargs: dict[str, Any] = {}
        if effect:
            kwargs.update(
                side_effect=effect[0],
                path=effect[1],
                path_ambiguous=effect[2],
                effect_observation="normalizer_inferred",
            )
        return Event(
            id=f"e{seq}",
            seq=seq,
            kind="command_start" if started else "command_end",
            actor="agent",
            tool="command_execution",
            status="started" if started else status,
            command=command,
            raw_ref=raw_ref,
            **kwargs,
        )
    if item_type == "agent_message" and completed:
        return Event(
            id=f"e{seq}",
            seq=seq,
            kind="agent_message",
            actor="agent",
            status="completed",
            text=_bounded_text(item.get("text")),
            raw_ref=raw_ref,
        )
    if item_type == "reasoning" and completed:
        return Event(
            id=f"e{seq}",
            seq=seq,
            kind="reasoning_summary",
            actor="agent",
            status="completed",
            text=_bounded_text(item.get("summary")),
            raw_ref=raw_ref,
        )
    if item_type in {"plan_update", "plan"} and completed:
        return Event(
            id=f"e{seq}",
            seq=seq,
            kind="plan_update",
            actor="agent",
            status="completed",
            text=_bounded_text(item.get("text", item.get("summary"))),
            raw_ref=raw_ref,
        )
    if item_type in {"mcp_tool_call", "mcp_call"} and (started or completed):
        args = _json_safe(item.get("arguments"))
        metadata = {
            key: item[key] for key in ("server", "tool", "name") if isinstance(item.get(key), str)
        }
        return Event(
            id=f"e{seq}",
            seq=seq,
            kind="mcp_call",
            actor="tool",
            tool=item.get("tool") if isinstance(item.get("tool"), str) else None,
            status="started" if started else status,
            arguments=args if isinstance(args, dict) else None,
            result_summary=_bounded_text(item.get("result_summary")),
            source_metadata=metadata or None,
            raw_ref=raw_ref,
        )
    if item_type in {"web_search", "web_search_call"} and (started or completed):
        return Event(
            id=f"e{seq}",
            seq=seq,
            kind="web_search",
            actor="tool",
            status="started" if started else status,
            side_effect="network" if completed and status == "completed" else "unknown",
            effect_observation="source_reported"
            if completed and status == "completed"
            else "unknown",
            text=_bounded_text(item.get("query")),
            raw_ref=raw_ref,
        )
    if item_type == "file_change" and (started or completed):
        changes = _file_changes(item)
        kinds = {change.kind for change in changes}
        side_effect: Literal["read", "write", "delete", "network", "none", "unknown"] = (
            "delete"
            if kinds == {"delete"}
            else "write"
            if kinds & {"create", "write"}
            else "unknown"
        )
        if started or status != "completed":
            side_effect = "unknown"
        return Event(
            id=f"e{seq}",
            seq=seq,
            kind="file_change",
            actor="agent",
            status="started" if started else status,
            side_effect=side_effect,
            changes=changes,
            effect_observation="source_reported"
            if completed and status == "completed"
            else "unknown",
            raw_ref=raw_ref,
        )
    return Event(id=f"e{seq}", seq=seq, kind="unknown", raw_ref=raw_ref)


def normalize_codex_jsonl_records(records: Sequence[Any]) -> tuple[Event, ...]:
    events: list[Event] = []
    for record in records:
        event = _event_from_record(record, len(events) + 1)
        if event is not None:
            events.append(event)
    return tuple(events)


def import_codex_jsonl(
    source: str | Path | IO[bytes],
    context: CodexCaseContext,
    *,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> Case:
    records, raw_source_sha256 = read_jsonl_bounded_with_sha256(
        source, max_line_bytes=max_line_bytes, max_records=max_records, invalid_utf8="error"
    )
    events = normalize_codex_jsonl_records(records)
    normalized = normalized_case_evidence(
        {
            "agent": context.agent,
            "task_user_request": context.task_user_request,
            "instruction_surfaces": context.instruction_surfaces,
            "events": events,
        }
    )
    evidence_sha256 = canonical_sha256(normalized)
    command_records: list[dict[str, Any]] = []
    for record in records:
        item = record.value.get("item")
        if isinstance(item, dict) and item.get("type") == "command_execution":
            command_records.append(item)
    command_text_complete = all(
        isinstance(item.get("command"), str) and bool(item.get("command", "").strip())
        for item in command_records
    )
    return Case(
        case_id=context.case_id,
        source=SourceProvenance(
            kind=SourceKind.CONTROLLED,
            origin_uri=context.origin_uri,
            license=context.license,
            redistribution_allowed=context.redistribution_allowed,
            raw_sha256=evidence_sha256,
            raw_source_sha256=raw_source_sha256,
            normalized_evidence_sha256=evidence_sha256,
            trace_format=TRACE_FORMAT,
            normalizer_version=NORMALIZER_VERSION,
        ),
        agent=context.agent,
        task_user_request=context.task_user_request,
        instruction_surfaces=context.instruction_surfaces,
        constraints=context.constraints,
        events=events,
        telemetry=TelemetryCapabilities(
            file_changes_observed=True,
            file_change_completeness="unknown",
            command_text_completeness="complete" if command_text_complete else "partial",
        ),
        starting_repo_tree=context.starting_repo_tree,
        filesystem_case_sensitive=context.filesystem_case_sensitive,
    )
