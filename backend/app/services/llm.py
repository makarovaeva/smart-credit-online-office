"""Формулировка ответа ИИ-агента моделью с открытыми весами через OpenAI-совместимый API
(Ollama, llama.cpp server, vLLM). Модель получает только факты из backend и шаблонный ответ:
решения и цифры она не придумывает, бизнес-команды не выполняет.

Не задан LLM_BASE_URL или модель не ответила - возвращается None, остаётся шаблон.
"""

import asyncio
import json
import logging
import urllib.request
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты - ИИ-кредитный агент банка в кабинете предпринимателя (малый бизнес).
Отвечай по-русски, вежливо и коротко: 1-4 предложения, без markdown-таблиц.
Опирайся только на факты ниже и на черновик ответа. Не придумывай суммы, ставки, сроки,
статусы, причины и документы, которых нет в фактах. Не обещай одобрение: решение по кредиту
принимает банк. Не проси пароли, коды и данные карт. Если черновик просит подтвердить
параметры или загрузить документы - сохрани эту просьбу.

Факты:
{facts}"""


def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"} | headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def model_name() -> str:
    return get_settings().llm_model


async def rephrase(
    facts: str, history: list[tuple[str, str]], question: str, draft: str
) -> str | None:
    settings = get_settings()
    if not settings.llm_base_url:
        return None
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(facts=facts)}]
    messages += [{"role": role, "content": content} for role, content in history]
    messages.append(
        {
            "role": "user",
            "content": f"{question}\n\n(Черновик ответа агента по данным банка: {draft})",
        }
    )
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    try:
        data = await asyncio.to_thread(
            _post,
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            {
                "model": settings.llm_model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 400,
            },
            headers,
            settings.llm_timeout_seconds,
        )
        text = data["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # сеть, тайм-аут, неожиданный формат ответа
        logger.warning("LLM недоступна, ответ по шаблону: %s", exc)
        return None
    return text[:2000] or None
