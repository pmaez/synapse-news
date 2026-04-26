from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Feed:
    id: str
    url: str
    title: str | None = None
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Feed":
        return cls(
            id=value["id"],
            url=value["url"],
            title=value.get("title"),
            enabled=value.get("enabled", True),
            tags=list(value.get("tags", [])),
            created_at=value.get("created_at", utc_now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "enabled": self.enabled,
            "tags": self.tags,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class LLMSettings:
    provider: str = "lmstudio"
    model: str = "local-model"
    base_url: str = "http://localhost:1234/v1"
    api_key: str | None = None
    api_key_env: str | None = None
    temperature: float = 0.2
    max_summary_tokens: int = 600
    max_scoring_tokens: int = 1024
    thinking_enabled: bool = False
    thinking_budget_tokens: int = 1024
    vision_enabled: bool = False
    reasoning_effort: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "LLMSettings":
        if not value:
            return cls()
        return cls(
            provider=value.get("provider", "lmstudio"),
            model=value.get("model", "local-model"),
            base_url=value.get("base_url", "http://localhost:1234/v1"),
            api_key=value.get("api_key"),
            api_key_env=value.get("api_key_env"),
            temperature=float(value.get("temperature", 0.2)),
            max_summary_tokens=int(value.get("max_summary_tokens", value.get("max_tokens", 600))),
            max_scoring_tokens=int(value.get("max_scoring_tokens", 1024)),
            thinking_enabled=bool(value.get("thinking_enabled", False)),
            thinking_budget_tokens=int(value.get("thinking_budget_tokens", 1024)),
            vision_enabled=bool(value.get("vision_enabled", False)),
            reasoning_effort=value.get("reasoning_effort"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "api_key_env": self.api_key_env,
            "temperature": self.temperature,
            "max_summary_tokens": self.max_summary_tokens,
            "max_scoring_tokens": self.max_scoring_tokens,
            "thinking_enabled": self.thinking_enabled,
            "thinking_budget_tokens": self.thinking_budget_tokens,
            "vision_enabled": self.vision_enabled,
            "reasoning_effort": self.reasoning_effort,
        }


@dataclass(slots=True)
class AppSettings:
    llm: LLMSettings = field(default_factory=LLMSettings)
    fetch_full_articles: bool = True
    request_timeout_seconds: float = 20.0
    retention_days: int | None = 7
    max_article_age_days: int | None = None
    user_agent: str = "SynapseNews/0.1"
    interests: list[str] = field(default_factory=list)
    min_relevance_score: int = 8

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "AppSettings":
        if not value:
            return cls()
        return cls(
            llm=LLMSettings.from_dict(value.get("llm")),
            fetch_full_articles=bool(value.get("fetch_full_articles", True)),
            request_timeout_seconds=float(value.get("request_timeout_seconds", 20.0)),
            retention_days=parse_optional_positive_days(value.get("retention_days", 7)),
            max_article_age_days=parse_optional_positive_days(value.get("max_article_age_days")),
            user_agent=value.get("user_agent", "SynapseNews/0.1"),
            interests=list(value.get("interests", [])),
            min_relevance_score=int(value.get("min_relevance_score", 8)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "llm": self.llm.to_dict(),
            "fetch_full_articles": self.fetch_full_articles,
            "request_timeout_seconds": self.request_timeout_seconds,
            "retention_days": self.retention_days,
            "max_article_age_days": self.max_article_age_days,
            "user_agent": self.user_agent,
            "interests": self.interests,
            "min_relevance_score": self.min_relevance_score,
        }


def parse_optional_positive_days(value: Any) -> int | None:
    if value is None:
        return None
    days = int(value)
    return days if days > 0 else None
