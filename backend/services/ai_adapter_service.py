from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

import requests
from sqlalchemy.exc import SQLAlchemyError

from backend.config.database import session_scope
from backend.repositories.ai_provider_repo import AIProviderRepository, PROVIDER_TYPES

# AI Provider architecture docs:
#   design/backend/ai-provider.md
# Keep that document in sync when changing provider types, adapter behavior, or routing semantics.

Message = dict[str, str]


def _provider_type_default(provider_type: str, key: str) -> str:
    for item in PROVIDER_TYPES:
        if item["code"] == provider_type:
            return item.get(key, "")
    return ""


@dataclass
class AIProviderConfig:
    provider_type: str
    base_url: str
    api_key: str
    model: str
    group_id: str = ""
    timeout_seconds: int = 120
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AIResponse:
    content: str
    raw: dict[str, Any]


class BaseAIAdapter:
    def __init__(self, config: AIProviderConfig):
        self.config = config

    def chat_completion(
        self,
        messages: list[Message],
        *,
        stream: bool = False,
        timeout: int | None = None,
        temperature: float | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> AIResponse:
        raise NotImplementedError


class MiniMaxAdapter(BaseAIAdapter):
    def chat_completion(
        self,
        messages: list[Message],
        *,
        stream: bool = False,
        timeout: int | None = None,
        temperature: float | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> AIResponse:
        base_url = self.config.base_url.rstrip("/") or "https://api.minimaxi.com"
        endpoint = "/v1/text/chatcompletion_v2" if stream else "/v1/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": stream,
        }
        if stream and self.config.group_id:
            payload["group_id"] = self.config.group_id
        if stream and not self.config.group_id:
            raise ValueError("MiniMax streaming chat requires group_id")
        if temperature is not None:
            payload["temperature"] = temperature
        return _post_chat_completion(
            url=f"{base_url}{endpoint}",
            api_key=self.config.api_key,
            payload=payload,
            stream=stream,
            timeout=timeout or self.config.timeout_seconds,
            on_chunk=on_chunk,
        )


class OpenAICompatibleAdapter(BaseAIAdapter):
    def chat_completion(
        self,
        messages: list[Message],
        *,
        stream: bool = False,
        timeout: int | None = None,
        temperature: float | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> AIResponse:
        base_url = self.config.base_url.rstrip("/")
        endpoint = self.config.extra.get("chat_endpoint") or "/v1/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        return _post_chat_completion(
            url=f"{base_url}{endpoint}",
            api_key=self.config.api_key,
            payload=payload,
            stream=stream,
            timeout=timeout or self.config.timeout_seconds,
            on_chunk=on_chunk,
        )


class DeepSeekAdapter(OpenAICompatibleAdapter):
    def chat_completion(
        self,
        messages: list[Message],
        *,
        stream: bool = False,
        timeout: int | None = None,
        temperature: float | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> AIResponse:
        if not self.config.base_url:
            self.config.base_url = "https://api.deepseek.com"
        if not self.config.model:
            self.config.model = "deepseek-v4-flash"
        self.config.extra.setdefault("chat_endpoint", "/chat/completions")
        return super().chat_completion(
            messages,
            stream=stream,
            timeout=timeout,
            temperature=temperature,
            on_chunk=on_chunk,
        )


class AnthropicAdapter(BaseAIAdapter):
    """Adapter for Anthropic-compatible APIs (e.g. MiMo)."""

    def chat_completion(
        self,
        messages: list[Message],
        *,
        stream: bool = False,
        timeout: int | None = None,
        temperature: float | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> AIResponse:
        base_url = self.config.base_url.rstrip("/")
        endpoint = self.config.extra.get("chat_endpoint") or "/v1/messages"
        max_tokens = self.config.extra.get("max_tokens", 4096)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        url = f"{base_url}{endpoint}"
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout or self.config.timeout_seconds)
        except requests.exceptions.Timeout as exc:
            raise ValueError(f"AI 请求超时 ({timeout or self.config.timeout_seconds}s)") from exc
        except requests.exceptions.ConnectionError as exc:
            raise ValueError(f"AI 网络连接失败: {exc}") from exc
        if response.status_code != 200:
            raise ValueError(f"AI 请求失败: {response.status_code} {response.text[:800]}")
        raw = response.json()
        return AIResponse(content=_extract_anthropic_content(raw), raw=raw)


def _extract_anthropic_content(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and isinstance(first.get("text"), str):
            return first["text"]
    if isinstance(payload.get("text"), str):
        return payload["text"]
    return ""


def _post_chat_completion(
    *,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    stream: bool,
    timeout: int,
    on_chunk: Callable[[str], None] | None,
) -> AIResponse:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout, stream=stream)
    except requests.exceptions.Timeout as exc:
        raise ValueError(f"AI 请求超时 ({timeout}s)") from exc
    except requests.exceptions.ConnectionError as exc:
        raise ValueError(f"AI 网络连接失败: {exc}") from exc
    if response.status_code != 200:
        raise ValueError(f"AI 请求失败: {response.status_code} {response.text[:800]}")
    if stream:
        content = _read_stream_content(response, on_chunk)
        return AIResponse(content=content, raw={"stream": True, "url": url})
    raw = response.json()
    return AIResponse(content=_extract_chat_content(raw), raw=raw)


def _read_stream_content(response: requests.Response, on_chunk: Callable[[str], None] | None) -> str:
    full_text = ""
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0] or {}
        delta = choice.get("delta") or {}
        message = choice.get("message") or {}
        delta_content = delta.get("content") or ""
        message_content = message.get("content") or ""
        if delta_content:
            full_text += delta_content
            if on_chunk:
                on_chunk(full_text)
            continue
        if message_content:
            if not full_text or message_content.startswith(full_text):
                full_text = message_content
                if on_chunk:
                    on_chunk(full_text)
    return full_text


def _extract_chat_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if isinstance(choices, list) and choices:
        first = choices[0] or {}
        message = first.get("message") if isinstance(first, dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        delta = first.get("delta") if isinstance(first, dict) else None
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            return delta["content"]
    for key in ("content", "text", "answer", "output"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, str):
            return value
    return ""


class AIAdapterRouter:
    def __init__(self):
        self._adapters = {
            "minimax": MiniMaxAdapter,
            "openai_compatible": OpenAICompatibleAdapter,
            "deepseek": DeepSeekAdapter,
            "anthropic_compatible": AnthropicAdapter,
        }

    def chat_completion(
        self,
        *,
        capability: str,
        messages: list[Message],
        fallback_model: str,
        fallback_provider_type: str = "minimax",
        fallback_base_url: str = "https://api.minimaxi.com",
        fallback_timeout: int = 120,
        stream: bool = False,
        temperature: float | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> AIResponse:
        config = self._resolve_config(
            capability=capability,
            fallback_model=fallback_model,
            fallback_provider_type=fallback_provider_type,
            fallback_base_url=fallback_base_url,
            fallback_timeout=fallback_timeout,
        )
        adapter_cls = self._adapters.get(config.provider_type)
        if not adapter_cls:
            raise ValueError(f"Unsupported AI provider_type: {config.provider_type}")
        return adapter_cls(config).chat_completion(
            messages,
            stream=stream,
            timeout=config.timeout_seconds,
            temperature=temperature,
            on_chunk=on_chunk,
        )

    def _resolve_config(
        self,
        *,
        capability: str,
        fallback_model: str,
        fallback_provider_type: str,
        fallback_base_url: str,
        fallback_timeout: int,
    ) -> AIProviderConfig:
        try:
            with session_scope() as db:
                binding, provider = AIProviderRepository(db).resolve_binding(capability)
                if provider:
                    api_key_env = provider.api_key_env or _provider_type_default(provider.provider_type, "api_key_env")
                    group_id_env = provider.group_id_env or _provider_type_default(provider.provider_type, "group_id_env")
                    api_key = provider.api_key or os.getenv(api_key_env or "") or ""
                    group_id = provider.group_id or os.getenv(group_id_env or "") or ""
                    model = (
                        (binding.model_override if binding else None)
                        or provider.default_model
                        or _provider_type_default(provider.provider_type, "default_model")
                        or fallback_model
                    )
                    if not api_key:
                        raise ValueError(f"AI provider {provider.code} has no api key")
                    return AIProviderConfig(
                        provider_type=provider.provider_type,
                        base_url=(
                            provider.base_url
                            or _provider_type_default(provider.provider_type, "default_base_url")
                            or fallback_base_url
                        ),
                        api_key=api_key,
                        model=model,
                        group_id=group_id,
                        timeout_seconds=provider.timeout_seconds or fallback_timeout,
                        extra=provider.extra or {},
                    )
        except (RuntimeError, SQLAlchemyError):
            pass

        api_key = os.getenv("MINIMAX_API_KEY") or ""
        group_id = os.getenv("MINIMAX_GROUP_ID") or ""
        if not api_key:
            raise ValueError("请设置 MINIMAX_API_KEY，或在 AI Provider 设置页配置可用 provider")
        return AIProviderConfig(
            provider_type=fallback_provider_type,
            base_url=fallback_base_url,
            api_key=api_key,
            model=fallback_model,
            group_id=group_id,
            timeout_seconds=fallback_timeout,
        )
