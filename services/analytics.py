"""Агрегаты для дашбордов Стадии 5. Считает поверх задач, записей времени и бюджетов.

Не заводит новых сущностей и не дублирует правила: часы берём из budgets.py.
"""
from decimal import Decimal

from sqlalchemy import extract, func

from constants import (
    STATUS_APPROVED,
    STATUS_CLARIFICATION,
    STATUS_ESTIMATE_PENDING,
    STATUS_IN_PROGRESS,
    STATUS_ACCEPTED,
    STATUS_DONE,
    TASK_STATUSES,
    WORK_TYPES,
)
from extensions import db
from models import Task, TimeEntry
from services.budgets import consumed_hours, effective_limit

ZERO = Decimal("0")

# Статусы, считающиеся «активными» для KPI клиента.
ACTIVE_STATUSES = {
    STATUS_ESTIMATE_PENDING,
    STATUS_APPROVED,
    STATUS_IN_PROGRESS,
    STATUS_CLARIFICATION,
}
DONE_STATUSES = {STATUS_DONE, STATUS_ACCEPTED}


def _dec(v) -> Decimal:
    if v is None:
        return ZERO
    return v if isinstance(v, Decimal) else Decimal(str(v))


def status_distribution(client_ids) -> dict:
    """{status: count} по всем задачам указанных клиентов (нули включены)."""
    result = {s: 0 for s in TASK_STATUSES}
    if not client_ids:
        return result
    rows = (
        db.session.query(Task.status, func.count(Task.id))
        .filter(Task.client_id.in_(client_ids))
        .group_by(Task.status)
        .all()
    )
    for status, count in rows:
        result[status] = count
    return result


def hours_by_work_type(client_ids, year, month) -> dict:
    """{work_type: Decimal} — списанные часы за месяц по типам работ (нули включены)."""
    result = {w: ZERO for w in WORK_TYPES}
    if not client_ids:
        return result
    rows = (
        db.session.query(Task.work_type, func.coalesce(func.sum(TimeEntry.hours), 0))
        .join(TimeEntry, TimeEntry.task_id == Task.id)
        .filter(
            Task.client_id.in_(client_ids),
            extract("year", TimeEntry.work_date) == year,
            extract("month", TimeEntry.work_date) == month,
        )
        .group_by(Task.work_type)
        .all()
    )
    for wt, hrs in rows:
        result[wt] = _dec(hrs)
    return result


def hours_by_client(clients, year, month) -> list:
    """[{'name', 'hours'}] — списанные часы за месяц по каждому клиенту (только > 0)."""
    result = []
    for org in clients:
        cons = consumed_hours(org.id, year, month)
        if cons > 0:
            result.append({"name": org.name, "hours": cons})
    result.sort(key=lambda r: r["hours"], reverse=True)
    return result


def client_balances(clients, year, month) -> list:
    """Баланс за месяц по каждому клиенту: лимит / расход / остаток / % заполнения."""
    balances = []
    for org in clients:
        eff = effective_limit(org.id, year, month)
        cons = consumed_hours(org.id, year, month)
        remaining = eff - cons
        pct = float(cons / eff * 100) if eff > 0 else (100.0 if cons > 0 else 0.0)
        balances.append(
            {
                "id": org.id,
                "name": org.name,
                "effective": eff,
                "consumed": cons,
                "remaining": remaining,
                "pct": pct,
                "over": remaining < 0,
                "warn": remaining >= 0 and pct >= 90,
            }
        )
    balances.sort(key=lambda b: b["pct"], reverse=True)
    return balances


def workload_summary(clients, year, month) -> dict:
    """Сводка нагрузки для дашборда методолога/админа за месяц."""
    balances = client_balances(clients, year, month)
    total_effective = sum((b["effective"] for b in balances), ZERO)
    total_consumed = sum((b["consumed"] for b in balances), ZERO)
    minus_count = sum(1 for b in balances if b["over"])
    return {
        "balances": balances,
        "total_effective": total_effective,
        "total_consumed": total_consumed,
        "total_remaining": total_effective - total_consumed,
        "minus_count": minus_count,
        "hours_by_client": hours_by_client(clients, year, month),
    }
