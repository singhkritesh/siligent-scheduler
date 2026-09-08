from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import settings

ALLOWED_TAGS = {
    "bleeding",
    "broken_tooth",
    "cold_sensitivity",
    "hot_sensitivity",
    "infection_concern",
    "lost_restoration",
    "pain",
    "routine_care",
    "swelling",
    "trauma",
}

TAG_PATTERNS = {
    "bleeding": ("bleeding", "blood"),
    "broken_tooth": ("broken tooth", "cracked tooth", "chipped tooth"),
    "cold_sensitivity": ("cold sensitive", "sensitive to cold"),
    "hot_sensitivity": ("hot sensitive", "sensitive to hot"),
    "infection_concern": ("infection", "pus", "abscess", "fever"),
    "lost_restoration": ("lost filling", "lost crown", "crown fell"),
    "pain": ("pain", "ache", "hurts", "throbbing"),
    "routine_care": ("routine", "checkup", "check-up", "cleaning"),
    "swelling": ("swelling", "swollen"),
    "trauma": ("trauma", "accident", "hit", "knocked out"),
}


@dataclass(frozen=True)
class IntakeResult:
    tags: tuple[str, ...]
    priority: str
    source: str
    confidence: float


def _rule_tags(text: str) -> set[str]:
    lowered = text.lower()
    return {
        tag
        for tag, phrases in TAG_PATTERNS.items()
        if any(phrase in lowered for phrase in phrases)
    }


def _policy_priority(tags: set[str], procedure_code: str, text: str) -> str:
    lowered = text.lower()
    if procedure_code == "emergency" or tags & {"trauma", "swelling", "infection_concern"}:
        return "urgent"
    if "severe" in lowered and "pain" in tags:
        return "urgent"
    if tags & {"pain", "bleeding", "broken_tooth", "lost_restoration"}:
        return "priority"
    if not text.strip():
        return "manual_review"
    return "routine"


def _local_model_tags(condition: str) -> tuple[set[str], float] | None:
    if not settings.local_model_enabled or not condition.strip():
        return None
    prompt = (
        "Extract dental condition tags from the text. Return only JSON with keys "
        "tags and confidence. Allowed tags: "
        + ", ".join(sorted(ALLOWED_TAGS))
        + ". Do not diagnose or recommend treatment. Text: "
        + condition[:2000]
    )
    payload = json.dumps(
        {
            "model": settings.local_model_id,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        settings.local_model_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
            parsed = json.loads(body.get("response", "{}"))
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        return None
    tags = {
        str(tag)
        for tag in parsed.get("tags", [])
        if str(tag) in ALLOWED_TAGS
    }
    try:
        confidence = min(1.0, max(0.0, float(parsed.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    return tags, confidence


def normalize_intake(condition: str, procedure_code: str) -> IntakeResult:
    sanitized = re.sub(r"\s+", " ", condition).strip()
    rule_tags = _rule_tags(sanitized)
    model_result = _local_model_tags(sanitized)
    if model_result:
        model_tags, confidence = model_result
        tags = rule_tags | model_tags
        source = settings.local_model_id
    else:
        tags = rule_tags
        confidence = 1.0 if tags else 0.5
        source = "clinician-policy-rules"
    return IntakeResult(
        tags=tuple(sorted(tags)),
        priority=_policy_priority(tags, procedure_code, sanitized),
        source=source,
        confidence=confidence,
    )
