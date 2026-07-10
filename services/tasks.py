"""Жизненный цикл задачи: явная матрица переходов + серверная валидация.

Кнопки в шаблоне лишь отражают матрицу; настоящая проверка роли и статуса —
здесь, на сервере. Любой переход вне матрицы или не той ролью → отказ.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from constants import (
    ROLE_ADMIN,
    ROLE_CLIENT,
    ROLE_METHODOLOGIST,
    STATUS_APPROVED,
    STATUS_CLARIFICATION,
    STATUS_DONE,
    STATUS_ESTIMATE_PENDING,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    STATUS_ACCEPTED,
    STATUS_REJECTED,
)

# Группа «сотрудников платформы»: методолог + админ (админ может всё, что методолог).
STAFF = (ROLE_METHODOLOGIST, ROLE_ADMIN)

# Требования к действию по вводу.
REQ_NONE = None
REQ_ESTIMATE = "estimate"          # обязательные часы оценки (> 0)
REQ_ESTIMATE_OPT = "estimate_opt"  # необязательная корректировка часов
REQ_COMMENT = "comment"            # обязательный текст-комментарий
REQ_REASON = "reason"              # обязательная причина

# Матрица переходов: action_key -> метаданные.
ACTIONS = {
    "set_estimate": {
        "label": "Поставить оценку",
        "roles": STAFF,
        "from": {STATUS_NEW},
        "to": STATUS_ESTIMATE_PENDING,
        "requires": REQ_ESTIMATE,
        "kind": "primary",
    },
    "approve_estimate": {
        "label": "Подтвердить оценку",
        "roles": (ROLE_CLIENT,),
        "from": {STATUS_ESTIMATE_PENDING},
        "to": STATUS_APPROVED,
        "requires": REQ_NONE,
        "kind": "primary",
    },
    "take": {
        "label": "Взять в работу",
        "roles": STAFF,
        "from": {STATUS_APPROVED},
        "to": STATUS_IN_PROGRESS,
        "requires": REQ_NONE,
        "kind": "primary",
    },
    "request_clarification": {
        "label": "Запросить уточнение",
        "roles": STAFF,
        "from": {STATUS_IN_PROGRESS},
        "to": STATUS_CLARIFICATION,
        "requires": REQ_COMMENT,
        "kind": "ghost",
    },
    "resume": {
        "label": "Вернуть в работу",
        "roles": STAFF,
        "from": {STATUS_CLARIFICATION},
        "to": STATUS_IN_PROGRESS,
        "requires": REQ_NONE,
        "kind": "primary",
    },
    "close": {
        "label": "Закрыть задачу",
        "roles": STAFF,
        "from": {STATUS_IN_PROGRESS},
        "to": STATUS_DONE,
        "requires": REQ_ESTIMATE_OPT,
        "kind": "primary",
    },
    "accept": {
        "label": "Принять",
        "roles": (ROLE_CLIENT, ROLE_ADMIN),
        "from": {STATUS_DONE},
        "to": STATUS_ACCEPTED,
        "requires": REQ_NONE,
        "kind": "primary",
    },
    "return": {
        "label": "Вернуть на доработку",
        "roles": (ROLE_CLIENT,),
        "from": {STATUS_DONE},
        "to": STATUS_IN_PROGRESS,
        "requires": REQ_COMMENT,
        "kind": "ghost",
    },
    "reject": {
        "label": "Отклонить",
        "roles": STAFF,
        "from": {
            STATUS_NEW,
            STATUS_ESTIMATE_PENDING,
            STATUS_APPROVED,
            STATUS_IN_PROGRESS,
            STATUS_CLARIFICATION,
        },
        "to": STATUS_REJECTED,
        "requires": REQ_REASON,
        "kind": "danger",
    },
}


class TransitionError(Exception):
    """Ошибка бизнес-валидации перехода (показать пользователю через flash)."""


def available_actions(task, user):
    """Список действий, доступных пользователю для текущего статуса задачи."""
    result = []
    for key, meta in ACTIONS.items():
        if user.role not in meta["roles"]:
            continue
        if task.status not in meta["from"]:
            continue
        result.append({"key": key, **meta})
    return result


def _parse_decimal(raw, label):
    if raw is None or str(raw).strip() == "":
        raise TransitionError(f"Поле «{label}» обязательно.")
    try:
        return Decimal(str(raw).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        raise TransitionError(f"Поле «{label}» должно быть числом.")


def apply_action(task, user, action_key, form, *, add_comment, notify_client, notify_staff):
    """Проверить и применить переход. Возвращает человекочитаемое сообщение об успехе.

    Побочные эффекты (комментарии, уведомления) выполняются через переданные
    колбэки, чтобы держать матрицу независимой от Flask/шаблонов.
    Бросает TransitionError при нарушении матрицы или требований ввода.
    """
    meta = ACTIONS.get(action_key)
    if meta is None:
        raise TransitionError("Неизвестное действие.")
    if user.role not in meta["roles"]:
        # Не та роль — жёсткий отказ (дублирует сокрытие кнопки в шаблоне).
        raise TransitionError("__forbidden__")
    if task.status not in meta["from"]:
        raise TransitionError("Действие недоступно для текущего статуса задачи.")

    requires = meta["requires"]
    comment_text = (form.get("comment") or "").strip()
    reason_text = (form.get("reason") or "").strip()

    # --- Валидация обязательного ввода ---
    if requires == REQ_ESTIMATE:
        hours = _parse_decimal(form.get("estimated_hours"), "Оценка часов")
        if hours <= 0:
            raise TransitionError("Оценка часов должна быть больше нуля.")
        task.estimated_hours = hours
    elif requires == REQ_ESTIMATE_OPT:
        raw = form.get("estimated_hours")
        if raw is not None and str(raw).strip() != "":
            hours = _parse_decimal(raw, "Оценка часов")
            if hours < 0:
                raise TransitionError("Оценка часов не может быть отрицательной.")
            task.estimated_hours = hours
    elif requires == REQ_COMMENT:
        if not comment_text:
            raise TransitionError("Требуется комментарий.")
    elif requires == REQ_REASON:
        if not reason_text:
            raise TransitionError("Укажите причину.")

    now = datetime.utcnow()
    prev_status = task.status
    task.status = meta["to"]
    task.updated_at = now

    # --- Служебные метки и побочные эффекты по действию ---
    if action_key == "set_estimate":
        notify_client(
            "estimate_set",
            f"Методолог оценил задачу «{task.title}» в {task.estimated_hours} ч — подтвердите оценку.",
        )
        return "Оценка выставлена, клиенту отправлено уведомление."

    if action_key == "approve_estimate":
        notify_staff("estimate_approved", f"Клиент подтвердил оценку задачи «{task.title}».")
        return "Оценка подтверждена."

    if action_key == "take":
        return "Задача взята в работу."

    if action_key == "request_clarification":
        add_comment(comment_text)
        notify_client("clarification", f"По задаче «{task.title}» нужен ответ (уточнение).")
        return "Запрошено уточнение, клиент уведомлён."

    if action_key == "resume":
        return "Задача возвращена в работу."

    if action_key == "close":
        task.closed_at = now
        notify_client("task_done", f"Задача «{task.title}» выполнена — примите работу.")
        return "Задача закрыта, клиенту отправлено уведомление о приёмке."

    if action_key == "accept":
        task.accepted_at = now
        notify_staff("task_accepted", f"Клиент принял задачу «{task.title}».")
        return "Задача принята."

    if action_key == "return":
        task.return_reason = comment_text
        task.closed_at = None  # снова в работе
        add_comment(f"Возврат на доработку: {comment_text}")
        notify_staff("task_returned", f"Клиент вернул задачу «{task.title}» на доработку.")
        return "Задача возвращена на доработку."

    if action_key == "reject":
        task.return_reason = reason_text
        add_comment(f"Отклонено: {reason_text}")
        notify_client("task_rejected", f"Задача «{task.title}» отклонена: {reason_text}")
        return "Задача отклонена."

    # На всякий случай — не должно случиться.
    task.status = prev_status
    raise TransitionError("Действие не обработано.")
