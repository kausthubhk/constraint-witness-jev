"""Offline publication checks for cases and sanitized JSON values."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .sanitize import SanitizationReport, sanitize_value


@dataclass(frozen=True)
class ReleaseIssue:
    code: str
    message: str
    path: str | None = None


@dataclass
class ReleaseCheck:
    issues: list[ReleaseIssue] = field(default_factory=list)
    sanitization: SanitizationReport | None = None

    @property
    def passed(self) -> bool:
        return not self.issues


def check_publication_value(value: Any, *, require_sanitized: bool = True) -> ReleaseCheck:
    """Check a candidate value without writing or contacting any service."""
    report = SanitizationReport()
    sanitized = sanitize_value(value, report=report)
    issues: list[ReleaseIssue] = []
    if require_sanitized and sanitized != value:
        issues.append(
            ReleaseIssue("unsanitized-content", "candidate contains content requiring redaction")
        )
    if report.findings:
        issues.extend(
            ReleaseIssue("sensitive-content", finding) for finding in sorted(set(report.findings))
        )
    return ReleaseCheck(issues, report)


def check_case_publication(case: Any) -> ReleaseCheck:
    """Apply publication posture checks to a case-like Pydantic object or dict.

    Unresolved redistribution permission is always reported.  The check does
    not invent a license or treat a raw hash as a license grant.
    """
    data = case.model_dump(mode="json", exclude_none=False) if hasattr(case, "model_dump") else case
    result = check_publication_value(data)
    source = data.get("source") if isinstance(data, dict) else None
    if not isinstance(source, dict):
        result.issues.append(
            ReleaseIssue("source-provenance-invalid", "source provenance is absent or malformed")
        )
        source = {}
    if source.get("redistribution_allowed") is not True:
        result.issues.append(
            ReleaseIssue(
                "publication-permission-unresolved",
                "source redistribution permission is not verified",
            )
        )
    if not source.get("license"):
        result.issues.append(ReleaseIssue("license-unresolved", "source license is not recorded"))
    return result


def check_publication_cases(cases: Iterable[Any]) -> ReleaseCheck:
    combined = ReleaseCheck()
    for case in cases:
        result = check_case_publication(case)
        combined.issues.extend(result.issues)
        if result.sanitization is None:
            continue
        if combined.sanitization is None:
            combined.sanitization = SanitizationReport()
        combined.sanitization.redactions += result.sanitization.redactions
        combined.sanitization.oversized_values += result.sanitization.oversized_values
        combined.sanitization.sensitive_fields += result.sanitization.sensitive_fields
        combined.sanitization.findings.extend(result.sanitization.findings)
    return combined


def _contains_provider_result(value: Any) -> bool:
    """Return true for stored semantic-provider rows or manifests."""
    if isinstance(value, Mapping):
        evaluator = value.get("evaluator")
        if isinstance(evaluator, Mapping) and (
            str(evaluator.get("evaluator_type", "")).startswith("jev") or evaluator.get("model_id")
        ):
            return True
        if any(
            key in value
            for key in (
                "raw_response_sha256",
                "provider_call_made",
                "provider_call_count",
                "call_id",
                "model_requested",
                "model_resolved",
            )
        ):
            return True
        return any(_contains_provider_result(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_provider_result(item) for item in value)
    return False


def check_provider_result_publication(
    value: Any, *, provider_publication_allowed: bool | None = None
) -> ReleaseCheck:
    """Fail closed when a run/report contains provider-derived results.

    Provider permission is deliberately separate from case redistribution
    permission. ``None`` means unresolved and therefore remains private.
    """
    result = check_publication_value(value)
    if _contains_provider_result(value) and provider_publication_allowed is not True:
        result.issues.append(
            ReleaseIssue(
                "provider-result-publication-permission-unresolved",
                "provider-result publication permission is unresolved; keep this artifact private",
            )
        )
    return result


def check_run_publication(
    rows: Sequence[Any] | Mapping[str, Any],
    *,
    provider_publication_allowed: bool | None = None,
) -> ReleaseCheck:
    """Public helper for CLI run/report release gates."""
    return check_provider_result_publication(
        rows, provider_publication_allowed=provider_publication_allowed
    )
