"""Сервисные функции учёта часов и месячных бюджетов.

Чистые переиспользуемые функции — база для Стадий 4–8 (расход, остаток, отчёты).
Все расчёты часов ведём через Decimal, чтобы не накапливать погрешность float.
"""
from decimal import Decimal

from sqlalchemy import extract, func
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import BudgetAdjustment, ClientOrg, MonthlyBudget, Task, TimeEntry

ZERO = Decimal("0")


def _to_decimal(value) -> Decimal:
    """Безопасное приведение к Decimal (значения Numeric из БД уже Decimal, float — нет)."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def get_or_create_monthly_budget(client_id, year, month, created_by=None) -> MonthlyBudget:
    """Вернуть запись месячного бюджета, создав из default_monthly_hours, если её нет.

    Идемпотентна: опирается на уникальный индекс (client_id, year, month) и
    аккуратно обрабатывает гонку (IntegrityError → откат и повторный запрос).
    """
    budget = MonthlyBudget.query.filter_by(
        client_id=client_id, year=year, month=month
    ).first()
    if budget is not None:
        return budget

    org = db.session.get(ClientOrg, client_id)
    default_hours = _to_decimal(org.default_monthly_hours) if org else ZERO

    budget = MonthlyBudget(
        client_id=client_id,
        year=year,
        month=month,
        base_limit_hours=default_hours,
        created_by=created_by,
    )
    db.session.add(budget)
    try:
        db.session.commit()
    except IntegrityError:
        # Параллельно уже создали такую запись — берём существующую.
        db.session.rollback()
        budget = MonthlyBudget.query.filter_by(
            client_id=client_id, year=year, month=month
        ).first()
    return budget


def sum_adjustments(client_id, year, month) -> Decimal:
    """Сумма ручных добавлений часов за месяц (может быть отрицательной)."""
    total = (
        db.session.query(func.coalesce(func.sum(BudgetAdjustment.delta_hours), 0))
        .filter_by(client_id=client_id, year=year, month=month)
        .scalar()
    )
    return _to_decimal(total)


def base_limit(client_id, year, month) -> Decimal:
    """Базовый лимит месяца: из monthly_budgets, иначе — default_monthly_hours клиента.

    Не создаёт записей (чистая функция). Для новых месяцев без явного бюджета
    базой считается значение по умолчанию организации.
    """
    budget = MonthlyBudget.query.filter_by(
        client_id=client_id, year=year, month=month
    ).first()
    if budget is not None:
        return _to_decimal(budget.base_limit_hours)
    org = db.session.get(ClientOrg, client_id)
    return _to_decimal(org.default_monthly_hours) if org else ZERO


def effective_limit(client_id, year, month) -> Decimal:
    """Эффективный лимит = базовый лимит месяца + Σ ручных добавлений за месяц."""
    return base_limit(client_id, year, month) + sum_adjustments(client_id, year, month)


def add_hours(client_id, year, month, delta_hours, reason, created_by) -> BudgetAdjustment:
    """Создать запись аудита добавления часов. base_limit_hours не мутируем."""
    adj = BudgetAdjustment(
        client_id=client_id,
        year=year,
        month=month,
        delta_hours=_to_decimal(delta_hours),
        reason=reason,
        created_by=created_by,
    )
    db.session.add(adj)
    db.session.commit()
    return adj


def consumed_hours(client_id, year, month) -> Decimal:
    """Расход часов за месяц = Σ time_entries.hours по всем задачам клиента,
    где work_date попадает в (year, month).

    Атрибуция строго по work_date записи, а не по дате закрытия задачи: задача,
    тянущаяся через границу месяца, распределяется по фактическим датам записей.
    """
    total = (
        db.session.query(func.coalesce(func.sum(TimeEntry.hours), 0))
        .join(Task, TimeEntry.task_id == Task.id)
        .filter(
            Task.client_id == client_id,
            extract("year", TimeEntry.work_date) == year,
            extract("month", TimeEntry.work_date) == month,
        )
        .scalar()
    )
    return _to_decimal(total)


def remaining_hours(client_id, year, month) -> Decimal:
    """Остаток = эффективный лимит − расход (может уходить в минус)."""
    return effective_limit(client_id, year, month) - consumed_hours(client_id, year, month)


def create_month_budgets_for_active_clients(year, month, created_by=None) -> int:
    """Создать месячный бюджет из default_monthly_hours для всех активных клиентов,
    у кого его ещё нет. Возвращает число созданных записей. Идемпотентна.
    """
    created = 0
    active_clients = ClientOrg.query.filter_by(is_active=True).all()
    for org in active_clients:
        existing = MonthlyBudget.query.filter_by(
            client_id=org.id, year=year, month=month
        ).first()
        if existing is None:
            get_or_create_monthly_budget(org.id, year, month, created_by)
            created += 1
    return created
