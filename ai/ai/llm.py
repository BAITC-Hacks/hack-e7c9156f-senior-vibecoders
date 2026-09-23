"""Единый клиент LLM: провайдеры OpenAI/NVIDIA, structured output, эмбеддинги, дисковый кэш.

Все вызовы моделей в пакете идут только через этот модуль.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import TypeVar, overload

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError

_PKG_ROOT = Path(__file__).resolve().parent
load_dotenv(_PKG_ROOT.parent / ".env")

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "openai").lower()


def model_name(strong: bool = False) -> str:
    if provider() == "nvidia":
        return os.environ["NVIDIA_MODEL"]
    if strong:
        return os.getenv("OPENAI_MODEL_STRONG") or os.getenv("OPENAI_MODEL", "gpt-5.4")
    return os.getenv("OPENAI_MODEL", "gpt-5.4-mini")


_clients: dict[str, OpenAI] = {}


def _client(kind: str | None = None) -> OpenAI:
    kind = kind or provider()
    if kind not in _clients:
        if kind == "nvidia":
            _clients[kind] = OpenAI(api_key=os.environ["NVIDIA_API_KEY"], base_url=NVIDIA_BASE_URL, timeout=180)
        else:
            _clients[kind] = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=180)
    return _clients[kind]


def _cache_dir() -> Path:
    d = Path(os.getenv("AI_CACHE_DIR", ".cache"))
    if not d.is_absolute():
        d = _PKG_ROOT.parent / d
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(*parts: object) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_reasoning_model(model: str) -> bool:
    # у reasoning-моделей нет параметра temperature
    return model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))


def load_prompt(name: str) -> str:
    return (_PKG_ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")


@overload
def call_llm(system: str, user: str, schema: type[T], *, strong: bool = False) -> T: ...
@overload
def call_llm(system: str, user: str, schema: None = None, *, strong: bool = False) -> str: ...


def call_llm(system: str, user: str, schema: type[T] | None = None, *, strong: bool = False):
    """Вызов модели. С `schema` возвращает валидированный Pydantic-объект, иначе текст."""
    model = model_name(strong)
    schema_sig = json.dumps(schema.model_json_schema(), sort_keys=True) if schema else None
    key = _cache_key("chat", provider(), model, system, user, schema_sig)
    path = _cache_dir() / f"{key}.json"
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        log.info("llm cache hit %s", key[:10])
        return schema.model_validate(cached) if schema else cached

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    extra = {} if _is_reasoning_model(model) else {"temperature": 0}
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            if schema is None:
                resp = _client().chat.completions.create(model=model, messages=messages, **extra)
                result: object = resp.choices[0].message.content or ""
                payload: object = result
            elif provider() == "openai":
                resp = _client().chat.completions.parse(model=model, messages=messages, response_format=schema, **extra)
                parsed = resp.choices[0].message.parsed
                if parsed is None:
                    raise ValueError(f"model refused or returned no parsed output: {resp.choices[0].message.refusal}")
                result, payload = parsed, parsed.model_dump(mode="json")
            else:
                # NVIDIA: JSON-режим + валидация по схеме
                sys_json = f"{system}\n\nОтветь ТОЛЬКО JSON по схеме:\n{schema_sig}"
                resp = _client().chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": sys_json}, messages[1]],
                    response_format={"type": "json_object"},
                    **extra,
                )
                result = schema.model_validate_json(resp.choices[0].message.content or "")
                payload = result.model_dump(mode="json")
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return result
        except (ValidationError, ValueError) as e:
            last_err = e
            log.warning("llm output invalid (attempt %d): %s", attempt + 1, e)
    raise RuntimeError(f"LLM не вернул валидный ответ: {last_err}")


def embed(texts: list[str]) -> np.ndarray:
    """Эмбеддинги (всегда OpenAI), нормированные; кэш по каждому тексту."""
    model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
    out: list[list[float] | None] = [None] * len(texts)
    missing: list[int] = []
    cache = _cache_dir() / "emb"
    cache.mkdir(exist_ok=True)
    for i, t in enumerate(texts):
        p = cache / f"{_cache_key('emb', model, t)}.json"
        if p.exists():
            out[i] = json.loads(p.read_text(encoding="utf-8"))
        else:
            missing.append(i)
    for start in range(0, len(missing), 256):
        batch = missing[start : start + 256]
        resp = _client("openai").embeddings.create(model=model, input=[texts[i] for i in batch])
        for i, d in zip(batch, resp.data):
            out[i] = d.embedding
            (cache / f"{_cache_key('emb', model, texts[i])}.json").write_text(json.dumps(d.embedding), encoding="utf-8")
    arr = np.array(out, dtype=np.float32)
    if arr.size == 0:
        return arr.reshape(0, 0)
    return arr / np.linalg.norm(arr, axis=1, keepdims=True)
