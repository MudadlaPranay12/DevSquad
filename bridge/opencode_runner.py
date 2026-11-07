"""
DEV-SQUAD — real local AI provider runner.

Uses the installed OpenCode CLI as the model provider. No mocked responses and
no hardcoded findings. The prompt is sent on stdin so large evidence bundles do
not hit Windows command-line length limits.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import PROJECT_ROOT, agent_model, agent_timeout_seconds, opencode_command

ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class OpenCodeError(RuntimeError):
    pass


@dataclass
class RunnerResult:
    text: str
    latency_ms: int
    session_id: Optional[str] = None
    token_usage: Optional[Dict[str, Any]] = None
    event_types: List[str] = field(default_factory=list)
    stderr: str = ""


def _resolve_command() -> List[str]:
    configured = opencode_command()
    resolved = shutil.which(configured) or configured
    if resolved.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", resolved]
    return [resolved]


def _safe_stderr(value: str) -> str:
    cleaned = ANSI_PATTERN.sub("", value or "")
    cleaned = cleaned.replace("\x00", "")
    return cleaned[:4000]


class OpenCodeRunner:
    """Invoke `opencode run --format json` once per agent turn."""

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        agent_name: str = "devsquad-analyst",
    ) -> None:
        self.model = model or agent_model()
        self.timeout = timeout or agent_timeout_seconds()
        self.agent_name = agent_name

    def _command(self, title: str) -> List[str]:
        command = _resolve_command() + [
            "run",
            "--format", "json",
            "--model", self.model,
            "--agent", self.agent_name,
            "--title", title[:120],
        ]
        return command

    def _run_sync(self, prompt: str, title: str) -> RunnerResult:
        started = time.monotonic()
        env = os.environ.copy()
        env.setdefault("NO_COLOR", "1")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            completed = subprocess.run(
                self._command(title),
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                cwd=str(PROJECT_ROOT),
                env=env,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as exc:
            raise OpenCodeError(
                f"OpenCode agent timed out after {self.timeout} seconds."
            ) from exc
        except FileNotFoundError as exc:
            raise OpenCodeError(
                "OpenCode CLI was not found. Install OpenCode or set DEV_SQUAD_OPENCODE."
            ) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        if completed.returncode != 0:
            raise OpenCodeError(
                "OpenCode exited with code "
                f"{completed.returncode}: {_safe_stderr(completed.stderr)}"
            )

        texts: List[str] = []
        event_types: List[str] = []
        session_id = None
        token_usage: Optional[Dict[str, Any]] = None

        for line in (completed.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type") or "")
            if event_type:
                event_types.append(event_type)
            if event.get("sessionID"):
                session_id = str(event["sessionID"])
            part = event.get("part") if isinstance(event.get("part"), dict) else {}
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
            if part.get("sessionID") and not session_id:
                session_id = str(part["sessionID"])
            for candidate in (event.get("tokens"), event.get("usage"), part.get("tokens"), part.get("usage")):
                if isinstance(candidate, dict):
                    token_usage = candidate

        text = "\n".join(texts).strip()
        if not text:
            raise OpenCodeError(
                "OpenCode returned no text response. stderr: "
                + _safe_stderr(completed.stderr)
            )
        return RunnerResult(
            text=text,
            latency_ms=latency_ms,
            session_id=session_id,
            token_usage=token_usage,
            event_types=event_types,
            stderr=_safe_stderr(completed.stderr),
        )

    def run(self, prompt: str, *, title: str = "DEV-SQUAD agent") -> RunnerResult:
        """Blocking call. The orchestrator runs this in a worker thread."""
        return self._run_sync(prompt, title)
