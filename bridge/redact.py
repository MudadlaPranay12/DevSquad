"""
DEV-SQUAD — second-stage redaction (redact.py)

Applies a second redaction pass after browser-side sanitization. All evidence
text, URLs, headers and storage values are treated as untrusted.

Never stores:
  - Cookie values or Set-Cookie values
  - Passwords
  - Authentication tokens, API keys or JWTs
  - Complete localStorage / sessionStorage contents
  - Request or response bodies
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

REDACTED = "[REDACTED]"
REDACTED_EMAIL = "[REDACTED_EMAIL]"
REDACTED_JWT = "[REDACTED_JWT]"
REDACTED_TOKEN = "[REDACTED_TOKEN]"
MAX_SCAN_LENGTH = 100_000

REDACTED_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "proxy-authorization",
    "x-csrf-token",
    "x-xsrf-token",
}

SENSITIVE_QUERY_PARAMS = {
    "api_key", "apikey", "api-key",
    "access_token", "accesstoken",
    "refresh_token", "refreshtoken",
    "auth_token", "authtoken",
    "session_token", "sessiontoken",
    "password", "passwd", "pwd",
    "secret", "client_secret", "clientsecret",
    "token", "code", "email",
}

SENSITIVE_KEYS = re.compile(
    r"^(password|passwd|pwd|secret|client_secret|api_key|apikey|api-key|"
    r"authorization|auth_token|access_token|refresh_token|session_token|"
    r"token|credential|credentials|cookie_value|cookievalue|set_cookie|"
    r"storage_value|localstorage|sessionstorage)$",
    re.IGNORECASE,
)

# Identifier-like fields must survive redaction so citations remain usable.
PRESERVE_KEYS = {
    "id", "legacy_id", "case_id", "schema_version", "source", "capture_source",
    "type", "timestamp", "timestamp_missing", "status", "method", "selector",
    "cookie_name", "cookie_domain", "cookie_secure", "cookie_http_only",
    "cookie_same_site", "redaction_applied", "evidence_ids", "agent_id",
    "message_type", "round", "url_path",
}

JWT_PATTERN = re.compile(r"ey[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+\b", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
API_KEY_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
]
KEY_VALUE_PATTERN = re.compile(
    r"\b(password|passwd|pwd|secret|token|api[_-]?key|client[_-]?secret)\s*[:=]\s*(\"[^\"]*\"|'[^']*'|\S+)",
    re.IGNORECASE,
)
PASSWORD_VALUE_PATTERN = re.compile(
    r"\b(password|passwd|pwd|secret|token|api[_-]?key|client[_-]?secret)\s+(\S+)",
    re.IGNORECASE,
)
AUTH_KEYWORDS = re.compile(
    r"\b(auth|authorization|login|password|signin|sign-in|credential|token|secret|session)\b",
    re.IGNORECASE,
)


def _redact_string(value: str, context: str = "") -> str:
    """Redact sensitive patterns inside one untrusted string."""
    if not isinstance(value, str) or not value:
        return value

    # Bound the amount of work a hostile evidence string can cause.
    result = value[:MAX_SCAN_LENGTH]
    was_truncated = len(value) > MAX_SCAN_LENGTH

    result = JWT_PATTERN.sub(REDACTED_JWT, result)
    result = BEARER_PATTERN.sub("Bearer " + REDACTED_TOKEN, result)
    for pattern in API_KEY_PATTERNS:
        result = pattern.sub(REDACTED, result)
    result = KEY_VALUE_PATTERN.sub(lambda m: f"{m.group(1)}={REDACTED}", result)
    result = PASSWORD_VALUE_PATTERN.sub(lambda m: f"{m.group(1)} {REDACTED}", result)

    if context in ("header", "url") or AUTH_KEYWORDS.search(result):
        result = EMAIL_PATTERN.sub(REDACTED_EMAIL, result)

    if was_truncated:
        result += " …[truncated during redaction]"
    return result


def redact_headers(headers: Dict[str, Any]) -> Dict[str, Any]:
    sanitized: Dict[str, Any] = {}
    for key, value in headers.items():
        if str(key).lower() in REDACTED_HEADERS:
            sanitized[key] = REDACTED
        elif isinstance(value, str):
            sanitized[key] = _redact_string(value, context="header")
        else:
            sanitized[key] = REDACTED
    return sanitized


def redact_url(url: str) -> str:
    """Redact sensitive query values while preserving the path and method."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return _redact_string(url, context="url")

    if not parsed.query:
        return _redact_string(url, context="url")

    params = parse_qs(parsed.query, keep_blank_values=True)
    new_params: Dict[str, List[str]] = {}
    for key, values in params.items():
        if key.lower() in SENSITIVE_QUERY_PARAMS:
            new_params[key] = [REDACTED]
        else:
            new_params[key] = [_redact_string(v, context="url") for v in values]

    new_query = urlencode(new_params, doseq=True)
    return urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, new_query, parsed.fragment,
    ))


def _redact_storage_map(value: Dict[str, Any]) -> Dict[str, Any]:
    """Keep storage key names, redact every value."""
    return {key: REDACTED for key in value.keys()}


def _redact_value(key: str, value: Any) -> Any:
    lower = key.lower()

    if key in PRESERVE_KEYS:
        return value
    if lower in {"legacy_id_map"} and isinstance(value, dict):
        return dict(value)

    if lower == "headers" and isinstance(value, dict):
        return redact_headers(value)
    if lower == "url" and isinstance(value, str):
        return redact_url(value)
    if lower in {"localstorage", "sessionstorage", "storage"} and isinstance(value, dict):
        return _redact_storage_map(value)
    if lower in {"cookie", "set-cookie", "set_cookie"}:
        return REDACTED

    if isinstance(value, str):
        if SENSITIVE_KEYS.match(key):
            return REDACTED
        if lower in {"message", "observation", "warnings", "incident_description", "title", "note", "reason", "question", "claim", "content"}:
            return _redact_string(value, context="message")
        if lower in {"path", "selector"}:
            return value
        return _redact_string(value, context="value")

    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    return value


def redact_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Apply second-stage redaction to an entire bundle."""
    redacted = copy.deepcopy(bundle)

    if isinstance(redacted.get("page_url"), str):
        redacted["page_url"] = redact_url(redacted["page_url"])

    evidence = redacted.get("evidence")
    if isinstance(evidence, list):
        redacted["evidence"] = [
            {k: _redact_value(k, v) for k, v in item.items()}
            if isinstance(item, dict) else item
            for item in evidence
        ]

    if isinstance(redacted.get("incident_description"), str):
        redacted["incident_description"] = _redact_string(
            redacted["incident_description"], context="message"
        )

    redacted["redaction_applied"] = True
    return redacted


# Backwards-compatible helper used by older tests.
def _redact_item_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _redact_value(k, v) for k, v in item.items()}
