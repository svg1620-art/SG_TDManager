"""Фрод-монитор: суммарные залогированные часы по методологам за день.

Считает по ИСПОЛНИТЕЛЮ (time_entries.methodologist_id), а не по текущему владельцу
клиента — переназначение клиента не искажает историю переработок.
"""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func

from constants import ROLE_METHODOLOGIST
from extensions import db
from models import TimeEntry, User

ZERO = Decimal("0")


def _dec(v) -> Decimal:
    if v is None:
        return ZERO
    return v if isinstance(v, Decimal) else Decimal(str(v))


def daily_hours_matrix(days=14):
    """Матрица «методолог × день» за последние `days` дней.

    Возвращает dict: dates (старые→новые), rows [{user, per_day{date: hours}, total}],
    и total_by_date. Строки — все, кто фигурирует как исполнитель в периоде,
    плюс активные методологи (даже с нулями).
    """
    today = date.today()
    start = today - timedelta(days=days - 1)
    dates = [start + timedelta(days=i) for i in range(days)]

    rows_q = (
        db.session.query(
            TimeEntry.methodologist_id,
            TimeEntry.work_date,
            func.coalesce(func.sum(TimeEntry.hours), 0),
        )
        .filter(TimeEntry.work_date >= start, TimeEntry.work_date <= today)
        .group_by(TimeEntry.methodologist_id, TimeEntry.work_date)
        .all()
    )

    # Соберём суммы и множество исполнителей.
    cell = {}
    user_ids = set()
    for mid, wdate, hrs in rows_q:
        cell[(mid, wdate)] = _dec(hrs)
        user_ids.add(mid)

    # Добавим активных методологов, даже если за период у них нет записей.
    active_methods = User.query.filter_by(
        role=ROLE_METHODOLOGIST, is_active=True
    ).all()
    user_ids.update(m.id for m in active_methods)

    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}

    rows = []
    for uid, user in sorted(users.items(), key=lambda kv: kv[1].full_name):
        per_day = {d: cell.get((uid, d), ZERO) for d in dates}
        rows.append(
            {
                "user_id": uid,
                "name": user.full_name,
                "is_active": user.is_active,
                "per_day": per_day,
                "total": sum(per_day.values(), ZERO),
            }
        )

    total_by_date = {
        d: sum((r["per_day"][d] for r in rows), ZERO) for d in dates
    }

    return {"dates": dates, "rows": rows, "total_by_date": total_by_date}


def today_totals():
    """Суммы часов по методологам за сегодня (крупный блок «сегодня»)."""
    today = date.today()
    rows_q = (
        db.session.query(
            TimeEntry.methodologist_id, func.coalesce(func.sum(TimeEntry.hours), 0)
        )
        .filter(TimeEntry.work_date == today)
        .group_by(TimeEntry.methodologist_id)
        .all()
    )
    totals = {mid: _dec(hrs) for mid, hrs in rows_q}
    user_ids = set(totals.keys())
    active_methods = User.query.filter_by(
        role=ROLE_METHODOLOGIST, is_active=True
    ).all()
    user_ids.update(m.id for m in active_methods)
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}

    result = [
        {"user_id": uid, "name": u.full_name, "hours": totals.get(uid, ZERO)}
        for uid, u in users.items()
    ]
    result.sort(key=lambda r: r["hours"], reverse=True)
    return result


def entries_for_day(methodologist_id, day):
    """Drill-down: записи времени исполнителя за конкретный день."""
    from models import ClientOrg, Task

    entries = (
        TimeEntry.query.filter_by(methodologist_id=methodologist_id, work_date=day)
        .order_by(TimeEntry.created_at.asc())
        .all()
    )
    rows = []
    for e in entries:
        task = db.session.get(Task, e.task_id)
        org = db.session.get(ClientOrg, task.client_id) if task else None
        rows.append(
            {
                "entry": e,
                "task": task,
                "client_name": org.name if org else "—",
            }
        )
    return rows
