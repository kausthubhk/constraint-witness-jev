"""Perform one small, sanitized Jev API connectivity check.

The credential is read only by this process from ``api_key.env``.  This script
does not print the credential, request headers, response body, or exceptions.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"
TIMEOUT_SECONDS = 10


def load_api_key(path: Path) -> str:
    """Load a bare token or TYPESAFE_API_KEY assignment without logging it."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if line.startswith("TYPESAFE_API_KEY="):
            value = line.split("=", 1)[1].strip()
        elif "=" not in line:
            value = line
        else:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value.strip()
    return ""


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    api_key = load_api_key(project_root / "api_key.env")
    if not api_key:
        print("preflight=failed reason=credential_unavailable")
        return 2

    payload = {
        "state": "The build completed successfully.",
        "model": MODEL,
        "questions": {
            "build_completed": {
                "type": "noul",
                "instructions": "Did the build complete successfully?",
            }
        },
    }
    request = Request(
        API_URL,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        print(f"preflight=failed status={error.code}")
        return 1
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        print("preflight=failed reason=request_or_response_error")
        return 1

    answer = result.get("answers", {}).get("build_completed", {})
    model = result.get("model")
    if status == 200 and isinstance(model, str) and answer.get("type") == "noul":
        print(f"preflight=success status={status} model={model} answer_type=noul")
        return 0

    print(f"preflight=failed status={status} reason=unexpected_response_shape")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
