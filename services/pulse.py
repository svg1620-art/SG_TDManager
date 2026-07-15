"""Ежедневный Telegram-пульс: сводка за день по клиенту.

День считается по московскому времени (Railway работает в UTC).
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func

from constants import STATUS_ACCEPTED, STATUS_CLARIFICATION, STATUS_IN_PROGRESS
from extensions import db
from models import ClientOrg, Task, TimeEntry
from services.budgets import consumed_hours, effective_limit
from services.telegram import escape, send_message

logger = logging.getLogger(__name__)

MSK = ZoneInfo("Europe/Moscow")

# Час ежедневной рассылки по МСК (env опционален, дефолт 19:00).
try:
    PULSE_HOUR = int(os.environ.get("PULSE_HOUR", "19"))
except (TypeError, ValueError):
    PULSE_HOUR = 19

# Не слать пустой пульс, если за день не было активности и списаний.
PULSE_SKIP_IF_EMPTY = True

ZERO = Decimal("0")


def today_msk():
    """Сегодняшняя дата по московскому времени."""
    return datetime.now(MSK).date()


def _utc_window_for_msk_day(day):
    """Границы московских суток `day` в наивном UTC (created_at/closed_at хранятся в UTC)."""
    start_msk = datetime(day.year, day.month, day.day, 0, 0, tzinfo=MSK)
    end_msk = start_msk + timedelta(days=1)
    to_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)
    return to_utc(start_msk), to_utc(end_msk)


def monthly_report_snippet(client, year, month):
    """Хук для Стадии 8: краткая выжимка месячного отчёта 5-го числа.

    TODO(Стадия 8): вернуть короткий текст выжимки AI-отчёта за (year, month).
    Пока всегда None — генерация отчёта не входит в Стадию 7.
    """
    return None


def build_digest(org, day):
    """Собрать HTML-текст дайджеста за день или None, если активности нет (при флаге)."""
    start_utc, end_utc = _utc_window_for_msk_day(day)

    created = Task.query.filter(
        Task.client_id == org.id,
        Task.created_at >= start_utc,
        Task.created_at < end_utc,
    ).count()
    done = Task.query.filter(
        Task.client_id == org.id,
        Task.closed_at.isnot(None),
        Task.closed_at >= start_utc,
        Task.closed_at < end_utc,
    ).count()
    accepted = Task.query.filter(
        Task.client_id == org.id,
        Task.accepted_at.isnot(None),
        Task.accepted_at >= start_utc,
        Task.accepted_at < end_utc,
    ).count()

    hours_today = (
        db.session.query(func.coalesce(func.sum(TimeEntry.hours), 0))
        .join(Task, TimeEntry.task_id == Task.id)
        .filter(Task.client_id == org.id, TimeEntry.work_date == day)
        .scalar()
    )
    hours_today = hours_today if isinstance(hours_today, Decimal) else Decimal(str(hours_today))

    # Сколько сейчас в активной работе (справочно).
    in_work = Task.query.filter(
        Task.client_id == org.id,
        Task.status.in_([STATUS_IN_PROGRESS, STATUS_CLARIFICATION]),
    ).count()

    eff = effective_limit(org.id, day.year, day.month)
    cons = consumed_hours(org.id, day.year, day.month)
    remaining = eff - cons

    has_activity = (created + done + accepted) > 0 or hours_today > 0
    if PULSE_SKIP_IF_EMPTY and not has_activity:
        return None

    def h(x):
        return f"{x:.1f}".rstrip("0").rstrip(".") if x == int(x) else f"{x:.2f}"

    lines = [
        f"<b>{escape(org.name)}</b> — пульс за {day.strftime('%d.%m.%Y')}",
        "",
    ]
    if has_activity:
        lines.append("<b>За сегодня:</b>")
        if created:
            lines.append(f"🆕 Создано задач: {created}")
        if done:
            lines.append(f"✅ Выполнено: {done}")
        if accepted:
            lines.append(f"🤝 Принято: {accepted}")
        lines.append(f"⏳ Списано часов: {h(hours_today)} ч")
        lines.append("")

    lines.append(f"Сейчас в работе: {in_work}")
    lines.append(f"Лимит месяца: {h(eff)} ч")
    lines.append(f"Потрачено: {h(cons)} ч")
    if remaining < 0:
        lines.append(f"⚠️ Остаток: минус {h(-remaining)} ч")
    else:
        lines.append(f"Остаток: {h(remaining)} ч")

    # Точка интеграции Стадии 8: 5-го числа добавляем выжимку месячного отчёта.
    if day.day == 5:
        snippet = monthly_report_snippet(org, day.year, day.month)
        if snippet:
            lines += ["", snippet]

    return "\n".join(lines)


def run_pulse(client_id=None):
    """Разослать пульс: одному клиенту (client_id) или всем активным с chat_id.

    Один сбойный клиент не блокирует рассылку остальным. Возвращает статистику.
    """
    day = today_msk()

    query = ClientOrg.query.filter_by(is_active=True)
    if client_id is not None:
        query = query.filter_by(id=client_id)
    clients = query.all()

    processed = sent = skipped = errors = 0
    for org in clients:
        processed += 1
        try:
            if not org.telegram_chat_id:
                skipped += 1
                continue
            text = build_digest(org, day)
            if text is None:
                skipped += 1
                continue
            if send_message(org.telegram_chat_id, text):
                sent += 1
            else:
                errors += 1
        except Exception as exc:  # noqa: BLE001 — один клиент не должен ронять рассылку
            errors += 1
            logger.exception("Ошибка пульса для клиента %s: %s", org.id, exc)

    logger.info(
        "Пульс за %s: обработано=%s, отправлено=%s, пропущено=%s, ошибок=%s",
        day,
        processed,
        sent,
        skipped,
        errors,
    )
    return {"processed": processed, "sent": sent, "skipped": skipped, "errors": errors}
