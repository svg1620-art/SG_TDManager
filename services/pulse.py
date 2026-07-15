"""Ежедневный Telegram-пульс: сводка за день по клиенту.

День считается по московскому времени (Railway работает в UTC).
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func

from constants import (
    ROLE_METHODOLOGIST,
    STATUS_ACCEPTED,
    STATUS_CLARIFICATION,
    STATUS_IN_PROGRESS,
)
from extensions import db
from models import ClientOrg, Task, TimeEntry, User
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


def _fmt_hours(x):
    return f"{x:.1f}".rstrip("0").rstrip(".") if x == int(x) else f"{x:.2f}"


def build_internal_digest(day):
    """Общий управленческий отчёт за день по методологам: создано/закрыто/принято/часы.

    Атрибуция задач — по владельцу клиента (client_orgs.methodologist_id),
    часы — по исполнителю записи (time_entries.methodologist_id).
    """
    start_utc, end_utc = _utc_window_for_msk_day(day)

    methods = (
        User.query.filter_by(role=ROLE_METHODOLOGIST, is_active=True)
        .order_by(User.full_name)
        .all()
    )

    rows = []
    tot_created = tot_closed = tot_accepted = 0
    tot_hours = ZERO
    for m in methods:
        client_ids = [
            c.id for c in ClientOrg.query.filter_by(methodologist_id=m.id).all()
        ]
        created = closed = accepted = 0
        if client_ids:
            created = Task.query.filter(
                Task.client_id.in_(client_ids),
                Task.created_at >= start_utc,
                Task.created_at < end_utc,
            ).count()
            closed = Task.query.filter(
                Task.client_id.in_(client_ids),
                Task.closed_at.isnot(None),
                Task.closed_at >= start_utc,
                Task.closed_at < end_utc,
            ).count()
            accepted = Task.query.filter(
                Task.client_id.in_(client_ids),
                Task.accepted_at.isnot(None),
                Task.accepted_at >= start_utc,
                Task.accepted_at < end_utc,
            ).count()

        hours = (
            db.session.query(func.coalesce(func.sum(TimeEntry.hours), 0))
            .filter(
                TimeEntry.methodologist_id == m.id, TimeEntry.work_date == day
            )
            .scalar()
        )
        hours = hours if isinstance(hours, Decimal) else Decimal(str(hours))

        rows.append(
            {
                "name": m.full_name,
                "created": created,
                "closed": closed,
                "accepted": accepted,
                "hours": hours,
            }
        )
        tot_created += created
        tot_closed += closed
        tot_accepted += accepted
        tot_hours += hours

    # Сортировка: сначала кто активнее (по часам, затем по закрытым).
    rows.sort(key=lambda r: (r["hours"], r["closed"], r["created"]), reverse=True)

    lines = [
        f"<b>Управленческий отчёт</b> — {day.strftime('%d.%m.%Y')}",
        f"Итого: 🆕 {tot_created} · ✅ {tot_closed} · 🤝 {tot_accepted} · ⏳ {_fmt_hours(tot_hours)} ч",
        "",
    ]
    if rows:
        for r in rows:
            lines.append(
                f"<b>{escape(r['name'])}</b>: "
                f"🆕 {r['created']} · ✅ {r['closed']} · 🤝 {r['accepted']} · "
                f"⏳ {_fmt_hours(r['hours'])} ч"
            )
    else:
        lines.append("Активных методологов нет.")

    return "\n".join(lines)


def run_internal_digest():
    """Отправить общий управленческий отчёт в общий чат. Возвращает статус."""
    from services import settings

    chat_id = settings.internal_digest_chat_id()
    if not chat_id:
        logger.info("Внутренний отчёт: общий chat_id не задан — пропуск.")
        return {"ok": False, "reason": "no_chat"}

    day = today_msk()
    text = build_internal_digest(day)
    ok = send_message(chat_id, text)
    logger.info("Внутренний отчёт за %s: отправлен=%s", day, ok)
    return {"ok": ok, "reason": "sent" if ok else "send_failed"}


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
