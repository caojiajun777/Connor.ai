"""Centralized id generation helpers."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from enum import Enum
from typing import Any


class IdPrefix(str, Enum):
    """Known persisted object id prefixes."""

    ARTIFACT = "art"
    CANDIDATE = "cand"
    CLUSTER = "cl"
    EVALUATION = "eval"
    EVIDENCE = "ev"
    MODEL_CALL = "model"
    RUN = "run"
    TOOL_CALL = "tool"
    TRACE_EVENT = "trace"


def deterministic_id(prefix: IdPrefix | str, payload: Any, *, length: int = 32) -> str:
    """Create a stable id from canonical JSON payload bytes."""

    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:length]
    return "_".join([_safe_part(_prefix_value(prefix)), digest])


def random_id(
    prefix: IdPrefix | str,
    *,
    parts: list[str] | tuple[str, ...] = (),
    length: int = 32,
) -> str:
    """Create a random id with a consistent prefix and optional semantic parts."""

    token = secrets.token_hex((length + 1) // 2)[:length]
    values = [_safe_part(_prefix_value(prefix))]
    values.extend(_safe_part(part) for part in parts if part)
    values.append(token)
    return "_".join(values)


def _prefix_value(prefix: IdPrefix | str) -> str:
    return prefix.value if isinstance(prefix, IdPrefix) else prefix


def _safe_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    if not safe:
        raise ValueError("id part cannot be empty")
    return safe
