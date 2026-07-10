"""Сервис записей времени: пересчёт кэша actual_hours по задаче."""
from decimal import Decimal

from sqlalchemy import func

from extensions import db
from models import Task, TimeEntry

ZERO = Decimal("0")


def recalc_task_actual(task_id) -> Decimal:
    """Пересчитать кэш tasks.actual_hours = Σ hours всех записей задачи (за всё время).

    Вызывать после ЛЮБОЙ мутации записей (добавление / изменение / удаление).
    Коммитит изменение actual_hours.
    """
    total = (
        db.session.query(func.coalesce(func.sum(TimeEntry.hours), 0))
        .filter(TimeEntry.task_id == task_id)
        .scalar()
    )
    total = total if isinstance(total, Decimal) else Decimal(str(total))

    task = db.session.get(Task, task_id)
    if task is not None:
        task.actual_hours = total
        db.session.commit()
    return total
