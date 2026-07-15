"""Жёсткое удаление задач и компаний (админ). Порядок удаления безопасен для FK.

Удаляем детей раньше родителей явными bulk-запросами, чтобы не полагаться на
поведение каскадов ORM и не ловить нарушения внешних ключей в PostgreSQL.
"""
from extensions import db
from models import (
    BudgetAdjustment,
    ClientOrg,
    ClientReassignment,
    Comment,
    MonthlyBudget,
    MonthlyReport,
    Notification,
    Task,
    TimeEntry,
    User,
)


def delete_task(task_id) -> None:
    """Удалить задачу со всеми связанными записями времени, комментариями и уведомлениями."""
    Notification.query.filter_by(task_id=task_id).delete(synchronize_session=False)
    Comment.query.filter_by(task_id=task_id).delete(synchronize_session=False)
    TimeEntry.query.filter_by(task_id=task_id).delete(synchronize_session=False)
    Task.query.filter_by(id=task_id).delete(synchronize_session=False)
    db.session.commit()


def delete_client(client_id) -> None:
    """Удалить компанию-клиента со всеми задачами, бюджетами, сотрудниками и историей.

    Порядок: уведомления/комментарии/время → задачи → сотрудники →
    бюджеты/добавления/отчёты/переназначения → сама организация.
    """
    task_ids = [t.id for t in Task.query.filter_by(client_id=client_id).all()]
    emp_ids = [u.id for u in User.query.filter_by(client_id=client_id).all()]

    if task_ids:
        Notification.query.filter(Notification.task_id.in_(task_ids)).delete(
            synchronize_session=False
        )
        Comment.query.filter(Comment.task_id.in_(task_ids)).delete(
            synchronize_session=False
        )
        TimeEntry.query.filter(TimeEntry.task_id.in_(task_ids)).delete(
            synchronize_session=False
        )
        Task.query.filter(Task.id.in_(task_ids)).delete(synchronize_session=False)

    if emp_ids:
        # Сначала уведомления сотрудников, затем сами учётки (задачи уже удалены).
        Notification.query.filter(Notification.user_id.in_(emp_ids)).delete(
            synchronize_session=False
        )
        User.query.filter(User.id.in_(emp_ids)).delete(synchronize_session=False)

    MonthlyBudget.query.filter_by(client_id=client_id).delete(synchronize_session=False)
    BudgetAdjustment.query.filter_by(client_id=client_id).delete(synchronize_session=False)
    MonthlyReport.query.filter_by(client_id=client_id).delete(synchronize_session=False)
    ClientReassignment.query.filter_by(client_id=client_id).delete(
        synchronize_session=False
    )
    ClientOrg.query.filter_by(id=client_id).delete(synchronize_session=False)
    db.session.commit()
