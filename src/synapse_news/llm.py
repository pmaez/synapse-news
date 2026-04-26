from __future__ import annotations

import os
import re
from typing import Any

import httpx

from .feeds import Article
from .models import LLMSettings


SCORE_SYSTEM_PROMPT = (
    "You evaluate news articles for relevance to a reader's interests. "
    "Do not think step by step. Do not include reasoning or preamble. "
    "Respond with exactly two lines: 'Score: N' (where N is 1-10) and 'Reason: one sentence.'"
)

SYSTEM_PROMPT = (
    "You summarize news articles accurately and concisely. "
    "Return only the final answer. Do not include chain-of-thought, hidden reasoning, analysis steps, "
    "drafting notes, or phrases like 'thinking process'. Do not invent details."
)
STRICT_SYSTEM_PROMPT = (
    "Return final answer only. Do not explain your reasoning. Do not include analysis, steps, drafts, "
    "or chain-of-thought. Start your response with 'Summary:'."
)


class LLMError(RuntimeError):
    pass


def api_key(settings: LLMSettings) -> str | None:
    if settings.api_key:
        return settings.api_key
    if settings.api_key_env:
        return os.environ.get(settings.api_key_env)
    if settings.provider == "openai":
        return os.environ.get("OPENAI_API_KEY")
    if settings.provider == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY")
    return None


def summarize(article: Article, settings: LLMSettings) -> str:
    if settings.provider == "none":
        return fallback_summary(article)
    if settings.provider in {"lmstudio", "openai", "openai-compatible"}:
        return summarize_openai_compatible(article, settings)
    if settings.provider == "anthropic":
        return summarize_anthropic(article, settings)
    raise LLMError(f"Unknown LLM provider: {settings.provider}")


def check_llm_available(settings: LLMSettings) -> None:
    if settings.provider == "none":
        return
    if settings.provider in {"lmstudio", "openai", "openai-compatible"}:
        check_openai_compatible_available(settings)
        return
    if settings.provider == "anthropic":
        if not api_key(settings):
            raise LLMError("Anthropic provider requires an API key or api_key_env.")
        return
    raise LLMError(f"Unknown LLM provider: {settings.provider}")


def check_openai_compatible_available(settings: LLMSettings) -> None:
    base_url = settings.base_url.rstrip("/")
    headers = {}
    key = api_key(settings)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        response = httpx.get(f"{base_url}/models", headers=headers, timeout=5)
        response.raise_for_status()
        if settings.provider == "lmstudio":
            model_ids = openai_compatible_model_ids(response.json())
            if model_ids and settings.model not in model_ids:
                available = ", ".join(model_ids)
                raise LLMError(
                    f"LM Studio is running, but configured model `{settings.model}` is not loaded. "
                    f"Available model(s): {available}. "
                    "Update it with `synapse-news config set-llm --model <model-id>`."
                )
    except httpx.ConnectError as exc:
        raise LLMError(
            f"Cannot connect to {settings.provider} at {base_url}. "
            "Start the local server, or update the provider/base URL with "
            "`synapse-news config set-llm`."
        ) from exc
    except httpx.TimeoutException as exc:
        raise LLMError(f"Timed out checking {settings.provider} at {base_url}.") from exc
    except httpx.HTTPStatusError as exc:
        raise LLMError(
            f"{settings.provider} at {base_url} returned HTTP {exc.response.status_code} during the LLM check: "
            f"{response_error_text(exc.response)}"
        ) from exc


def openai_compatible_model_ids(data: dict[str, Any]) -> list[str]:
    return [item["id"] for item in data.get("data", []) if isinstance(item, dict) and item.get("id")]


def response_error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:1000]
    return str(data)[:1000]


def summarize_openai_compatible(article: Article, settings: LLMSettings) -> str:
    base_url = settings.base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    key = api_key(settings)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = openai_compatible_payload(article, settings, SYSTEM_PROMPT, settings.max_summary_tokens)
    data = post_openai_compatible(base_url, headers, payload, settings.provider)
    summary = extract_openai_compatible_text(data)
    if summary:
        return summary

    retry_tokens = max(settings.max_summary_tokens, 1200)
    retry_payload = openai_compatible_payload(article, settings, STRICT_SYSTEM_PROMPT, retry_tokens)
    retry_data = post_openai_compatible(base_url, headers, retry_payload, settings.provider)
    retry_summary = extract_openai_compatible_text(retry_data)
    if retry_summary:
        return retry_summary

    raise LLMError(
        f"{settings.provider} returned an empty summary after retry. "
        "Try a different loaded model, increase --max-tokens, or inspect LM Studio server logs."
    )


def openai_compatible_payload(article: Article, settings: LLMSettings, system_prompt: str, max_tokens: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": settings.model,
        "temperature": settings.temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_for(article)},
        ],
    }
    if settings.reasoning_effort:
        payload["reasoning_effort"] = settings.reasoning_effort
    return payload


def post_openai_compatible(base_url: str, headers: dict[str, str], payload: dict[str, Any], provider: str) -> dict[str, Any]:
    try:
        response = httpx.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=60)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMError(
            f"{provider} returned HTTP {exc.response.status_code} from /chat/completions: "
            f"{response_error_text(exc.response)}"
        ) from exc
    return response.json()


def extract_openai_compatible_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        text = clean_summary_text(_strip_thinking_tags(content))
        if text:
            return text
    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, dict):
                chunks.append(str(item.get("text") or item.get("content") or ""))
        text = clean_summary_text(_strip_thinking_tags("\n".join(chunk for chunk in chunks if chunk)))
        if text:
            return text
    text = choices[0].get("text")
    return clean_summary_text(_strip_thinking_tags(text)) if isinstance(text, str) else ""


def clean_summary_text(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    lower_text = text.lower()
    heading_index = first_final_heading_index(text)
    if heading_index is not None and heading_index > 0:
        return text[heading_index:].strip()
    if "thinking process" in lower_text or "analyze the request" in lower_text:
        return ""
    return text


def first_final_heading_index(text: str) -> int | None:
    headings = ("summary:", "why it matters:", "key topics:", "key entities:")
    lower_text = text.lower()
    indexes = [lower_text.find(heading) for heading in headings if lower_text.find(heading) >= 0]
    return min(indexes) if indexes else None


def summarize_anthropic(article: Article, settings: LLMSettings) -> str:
    key = api_key(settings)
    if not key:
        raise LLMError("Anthropic provider requires an API key or api_key_env.")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }
    payload: dict[str, Any] = {
        "model": settings.model,
        "max_tokens": settings.max_summary_tokens,
        "temperature": settings.temperature,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt_for(article)}],
    }
    if settings.thinking_enabled:
        payload["thinking"] = {"type": "enabled", "budget_tokens": settings.thinking_budget_tokens}
    response = httpx.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    chunks = [item.get("text", "") for item in data.get("content", []) if item.get("type") == "text"]
    summary = clean_summary_text("\n".join(chunks))
    if not summary:
        raise LLMError("Anthropic returned an empty summary.")
    return summary


def prompt_for(article: Article) -> str:
    return f"""Title: {article.title}
Feed: {article.feed_title}
Published: {article.published or "unknown"}
URL: {article.url}

Article text:
{article.content}

Return exactly these three sections and nothing else:

Summary:
2-4 sentences.

Why it matters:
1-2 sentences.

Key topics:
Comma-separated entities or topics.
"""


def score_article(
    article: Article,
    settings: LLMSettings,
    interests: list[str],
    starred_titles: list[str],
    downvoted_titles: list[str] | None = None,
) -> tuple[int, str]:
    if settings.provider == "none" or not interests:
        return 5, ""
    prompt = _build_score_prompt(article, interests, starred_titles, downvoted_titles or [])
    if settings.provider in {"lmstudio", "openai", "openai-compatible"}:
        raw = _score_openai_compatible(prompt, settings)
    elif settings.provider == "anthropic":
        raw = _score_anthropic(prompt, settings)
    else:
        return 5, ""
    return _parse_score_response(raw)


def _build_score_prompt(
    article: Article,
    interests: list[str],
    starred_titles: list[str],
    downvoted_titles: list[str] | None = None,
) -> str:
    interests_str = ", ".join(interests)
    liked_section = ""
    if starred_titles:
        examples = "\n".join(f"- {t}" for t in starred_titles[:8])
        liked_section = f"\nThe reader has previously upvoted (liked) these articles:\n{examples}\n"
    disliked_section = ""
    if downvoted_titles:
        examples = "\n".join(f"- {t}" for t in downvoted_titles[:8])
        disliked_section = f"\nThe reader has previously downvoted (disliked) these articles:\n{examples}\n"
    return (
        f"Rate this article's relevance to the reader on a scale of 1-10.\n\n"
        f"Reader interests: {interests_str}{liked_section}{disliked_section}\n\n"
        f"Article:\n"
        f"Title: {article.title}\n"
        f"Source: {article.feed_title}\n"
        f"Published: {article.published or 'unknown'}\n"
        f"Text: {article.content[:1500]}\n\n"
        f"Respond with exactly two lines:\n"
        f"Score: <number 1-10>\n"
        f"Reason: <one sentence>"
    )


def _score_openai_compatible(prompt: str, settings: LLMSettings) -> str:
    base_url = settings.base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    key = api_key(settings)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload: dict[str, Any] = {
        "model": settings.model,
        "temperature": 0.1,
        "max_tokens": settings.max_scoring_tokens,
        "messages": [
            {"role": "system", "content": SCORE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    data = post_openai_compatible(base_url, headers, payload, settings.provider)
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if os.environ.get("SYNAPSE_DEBUG"):
        print(f"[debug score raw] finish_reason={choices[0].get('finish_reason')!r} content={content!r}")
    if isinstance(content, str) and content.strip():
        cleaned = _strip_thinking_tags(content)
        if cleaned:
            return cleaned
    # Reasoning models (e.g. Gemma thinking variants) put output in reasoning_content
    # when content tokens are exhausted; extract score from there as fallback.
    reasoning = message.get("reasoning_content")
    return reasoning.strip() if isinstance(reasoning, str) else ""


def _score_anthropic(prompt: str, settings: LLMSettings) -> str:
    key = api_key(settings)
    if not key:
        raise LLMError("Anthropic provider requires an API key.")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }
    payload: dict[str, Any] = {
        "model": settings.model,
        "max_tokens": settings.max_scoring_tokens,
        "temperature": 0.1,
        "system": SCORE_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    response = httpx.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    chunks = [item.get("text", "") for item in data.get("content", []) if item.get("type") == "text"]
    return _strip_thinking_tags("\n".join(chunks))


def _strip_thinking_tags(text: str) -> str:
    # Strip complete blocks first
    text = re.sub(r'<think(?:ing)?>\s*.*?\s*</think(?:ing)?>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Strip unclosed blocks (thinking truncated by token limit — no closing tag)
    text = re.sub(r'<think(?:ing)?>.*', '', text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _parse_score_response(text: str) -> tuple[int, str]:
    score: int | None = None
    reason = ""

    for line in text.strip().splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("score:"):
            try:
                score = max(1, min(10, int(stripped.split(":", 1)[1].strip().split()[0])))
            except (ValueError, IndexError):
                pass
        elif lower.startswith("reason:"):
            reason = stripped.split(":", 1)[1].strip()

    if score is None:
        # "7/10" or "7 / 10"
        m = re.search(r'\b(10|[1-9])\s*/\s*10\b', text)
        if m:
            score = int(m.group(1))

    if score is None:
        # "score of 7", "rated 8", "rating: 9", "relevance: 6"
        m = re.search(r'(?:score|rated?|rating|relevance)[^\d]*(10|[1-9])\b', text, re.IGNORECASE)
        if m:
            score = int(m.group(1))

    if score is None:
        # last resort: first standalone integer 1-10 in the response
        m = re.search(r'\b(10|[1-9])\b', text)
        if m:
            score = int(m.group(1))

    return score if score is not None else 5, reason


def fallback_summary(article: Article) -> str:
    text = article.content or article.excerpt
    sentences = [part.strip() for part in text.replace("\n", " ").split(".") if part.strip()]
    summary = ". ".join(sentences[:3])
    if summary:
        summary += "."
    return summary or article.title
