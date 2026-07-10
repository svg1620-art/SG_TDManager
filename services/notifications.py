"""Сервис in-app уведомлений (колокольчик). Переиспользуется в следующих стадиях."""
from extensions import db
from models import Notification


def notify(user_id, type, body, task_id=None):
    """Создать уведомление пользователю. Тихо игнорирует пустой user_id."""
    if not user_id:
        return None
    n = Notification(
        user_id=user_id,
        type=type,
        body=body,
        task_id=task_id,
        is_read=False,
    )
    db.session.add(n)
    db.session.commit()
    return n


def unread_count(user_id) -> int:
    if not user_id:
        return 0
    return Notification.query.filter_by(user_id=user_id, is_read=False).count()


def recent(user_id, limit=10):
    if not user_id:
        return []
    return (
        Notification.query.filter_by(user_id=user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )


def mark_read(notification_id, user_id) -> bool:
    n = Notification.query.filter_by(id=notification_id, user_id=user_id).first()
    if n is None:
        return False
    if not n.is_read:
        n.is_read = True
        db.session.commit()
    return True


def mark_all_read(user_id) -> int:
    updated = (
        Notification.query.filter_by(user_id=user_id, is_read=False)
        .update({"is_read": True})
    )
    db.session.commit()
    return updated
