"""Отправка сообщений в Telegram (push-only) через Bot API.

Токен — из TELEGRAM_BOT_TOKEN. Без токена функции логируют предупреждение и не падают.
Ошибки Telegram логируются, но не роняют вызывающий код (рассылку остальным клиентам).
"""
import html
import logging

import requests
from flask import current_app

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 10


def _token():
    try:
        return current_app.config.get("TELEGRAM_BOT_TOKEN") or ""
    except RuntimeError:
        # Вне контекста приложения.
        import os

        return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def escape(text) -> str:
    """Экранировать пользовательский текст под parse_mode=HTML."""
    return html.escape(str(text if text is not None else ""), quote=False)


def send_message(chat_id, text) -> bool:
    """Отправить сообщение в чат. Возвращает True при успехе, иначе False (без исключений)."""
    token = _token()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — сообщение не отправлено.")
        return False
    if not chat_id:
        logger.warning("Пустой chat_id — сообщение не отправлено.")
        return False

    url = API_BASE.format(token=token, method="sendMessage")
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": str(chat_id),
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code == 200 and data.get("ok"):
            return True
        logger.error(
            "Telegram sendMessage не удался: HTTP %s, ответ: %s",
            resp.status_code,
            data or resp.text,
        )
        return False
    except requests.RequestException as exc:
        logger.error("Ошибка сети при отправке в Telegram: %s", exc)
        return False


def get_updates():
    """Список последних чатов, откуда бота видели (для определения chat_id).

    Возвращает список dict {id, title, type} без дублей. Не поллинг — разовый вызов.
    """
    token = _token()
    if not token:
        return {"ok": False, "error": "no_token", "chats": []}

    url = API_BASE.format(token=token, method="getUpdates")
    try:
        resp = requests.get(url, params={"limit": 100}, timeout=TIMEOUT)
        data = resp.json() if resp.content else {}
        if resp.status_code != 200 or not data.get("ok"):
            logger.error("Telegram getUpdates не удался: %s", data or resp.text)
            return {"ok": False, "error": "api_error", "chats": []}

        seen = {}
        for upd in data.get("result", []):
            msg = (
                upd.get("message")
                or upd.get("edited_message")
                or upd.get("channel_post")
                or {}
            )
            chat = msg.get("chat")
            if not chat:
                continue
            cid = chat.get("id")
            if cid in seen:
                continue
            title = chat.get("title") or " ".join(
                filter(None, [chat.get("first_name"), chat.get("last_name")])
            ) or chat.get("username") or "—"
            seen[cid] = {"id": cid, "title": title, "type": chat.get("type")}
        return {"ok": True, "chats": list(seen.values())}
    except requests.RequestException as exc:
        logger.error("Ошибка сети при getUpdates: %s", exc)
        return {"ok": False, "error": "network", "chats": []}
