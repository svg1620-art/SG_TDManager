"""Отправка сообщений в Telegram (push-only) через Bot API.

Токен — из TELEGRAM_BOT_TOKEN. Без токена функции логируют предупреждение и не падают.
Ошибки Telegram логируются, но не роняют вызывающий код (рассылку остальным клиентам).
"""
import html
import logging
import threading

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


# Типы обновлений, из которых извлекаем chat. my_chat_member приходит при
# добавлении/изменении статуса бота в группе — не требует текстового сообщения.
_CHAT_CARRIERS = (
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "my_chat_member",
    "chat_member",
    "callback_query",
)


def _delete_webhook_if_any(token):
    """Если на боте висит webhook, getUpdates не работает — снимаем его (pending сохраняем)."""
    try:
        info = requests.get(
            API_BASE.format(token=token, method="getWebhookInfo"), timeout=TIMEOUT
        ).json()
        if info.get("ok") and info.get("result", {}).get("url"):
            requests.get(
                API_BASE.format(token=token, method="deleteWebhook"),
                params={"drop_pending_updates": "false"},
                timeout=TIMEOUT,
            )
            logger.info("Снят активный webhook, чтобы работал getUpdates.")
    except requests.RequestException:
        pass


def _extract_chat(update):
    for key in _CHAT_CARRIERS:
        payload = update.get(key)
        if not payload:
            continue
        chat = payload.get("chat") or (payload.get("message") or {}).get("chat")
        if chat:
            return chat
    return None


def _safe_send(token, chat_id, text):
    """Отправка из фонового потока: токен передан заранее (нет app-контекста в потоке)."""
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — instant-сообщение не отправлено.")
        return
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
        if resp.status_code != 200 or not (resp.json() if resp.content else {}).get("ok"):
            logger.error("Instant Telegram не доставлен: %s", resp.text)
    except Exception as exc:  # noqa: BLE001 — фон не должен ничего ронять
        logger.error("Ошибка фоновой отправки в Telegram: %s", exc)


def send_async(chat_id, text) -> None:
    """Fire-and-forget отправка в отдельном daemon-потоке.

    Токен читаем здесь (в контексте приложения/запроса) и передаём в поток, т.к.
    внутри потока current_app недоступен. Провал доставки не влияет на вызвавший код.
    """
    if not chat_id:
        return
    token = _token()
    thread = threading.Thread(
        target=_safe_send, args=(token, chat_id, text), daemon=True
    )
    thread.start()


def get_updates():
    """Список последних чатов, где бот фигурировал (для определения chat_id).

    Ловит и обычные сообщения, и событие добавления бота в группу (my_chat_member),
    поэтому id группы можно получить, просто добавив бота (без текстового сообщения).
    Возвращает {ok, chats:[{id,title,type}], error?}.
    """
    token = _token()
    if not token:
        return {"ok": False, "error": "no_token", "chats": []}

    _delete_webhook_if_any(token)

    url = API_BASE.format(token=token, method="getUpdates")
    try:
        resp = requests.get(
            url,
            params={
                "limit": 100,
                "allowed_updates": '["message","edited_message","channel_post","my_chat_member","chat_member"]',
            },
            timeout=TIMEOUT,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code != 200 or not data.get("ok"):
            logger.error("Telegram getUpdates не удался: %s", data or resp.text)
            return {"ok": False, "error": "api_error", "chats": []}

        seen = {}
        for upd in data.get("result", []):
            chat = _extract_chat(upd)
            if not chat:
                continue
            cid = chat.get("id")
            if cid is None or cid in seen:
                continue
            title = (
                chat.get("title")
                or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
                or chat.get("username")
                or "—"
            )
            seen[cid] = {"id": cid, "title": title, "type": chat.get("type")}
        return {"ok": True, "chats": list(seen.values())}
    except requests.RequestException as exc:
        logger.error("Ошибка сети при getUpdates: %s", exc)
        return {"ok": False, "error": "network", "chats": []}
