"""Единая точка испускания событий по задачам для мгновенных Telegram-оповещений.

Колокольчик (in-app) остаётся источником истины и формируется на прежних местах;
здесь — только instant-сообщения в группу клиента, испускаемые в тех же точках,
чтобы каналы не разъезжались. Доставка неблокирующая (fire-and-forget).
"""
import logging

from flask import current_app, url_for

from services.telegram import escape, send_async

logger = logging.getLogger(__name__)

# Комментарии методолога/админа тоже шлём в группу (можно отключить).
PUSH_COMMENTS = True

# event_type -> (эмодзи, шаблон, требуется_действие_клиента)
EVENT_SPECS = {
    "new": ("🆕", "Новая задача поставлена: «{title}»", False),
    "estimate_pending": ("💬", "По задаче «{title}» выставлена оценка {est} ч", True),
    "approved": ("✅", "Оценка подтверждена, задача в очереди: «{title}»", False),
    "in_progress": ("⏳", "Задача «{title}» в работе", False),
    "clarification": ("❓", "По задаче «{title}» нужен ваш ответ", True),
    "done": ("📦", "Задача «{title}» выполнена", True),
    "accepted": ("✅", "Задача «{title}» принята", False),
    "rejected": ("🚫", "Задача «{title}» отклонена. Причина: {reason}", False),
    "comment": ("💬", "Новый комментарий по задаче «{title}»", False),
}


def _task_url(task):
    base = current_app.config.get("APP_BASE_URL", "")
    if not base:
        logger.warning("APP_BASE_URL не задан — Telegram-ссылка на задачу не сформирована.")
        return None
    try:
        return base + url_for("tasks.task_detail", task_id=task.id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Не удалось сформировать ссылку на задачу: %s", exc)
        return None


def _fmt_est(task):
    if task.estimated_hours is None:
        return "—"
    v = float(task.estimated_hours)
    return f"{v:.1f}".rstrip("0").rstrip(".") if v == int(v) else f"{v:.2f}"


def emit_task_event(task, event_type, actor=None):
    """Отправить instant-сообщение в группу клиента (если включено и задан chat_id).

    Ничего не бросает наружу: любые проблемы логируются, переход не затрагивается.
    """
    try:
        spec = EVENT_SPECS.get(event_type)
        if spec is None:
            return
        org = task.client
        if org is None:
            return
        if not org.telegram_chat_id or not org.instant_notifications_enabled:
            return

        emoji, template, requires_action = spec
        body = f"{emoji} " + template.format(
            title=escape(task.title),
            est=_fmt_est(task),
            reason=escape(task.return_reason or "—"),
        )
        lines = [body]
        if requires_action:
            lines.append("⚠️ Требуется ваше действие")
        link = _task_url(task)
        if link:
            lines.append(f'<a href="{link}">Открыть задачу</a>')

        send_async(org.telegram_chat_id, "\n".join(lines))
    except Exception as exc:  # noqa: BLE001 — событие не должно ломать основной поток
        logger.error("Ошибка emit_task_event (%s): %s", event_type, exc)
