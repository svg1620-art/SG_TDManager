"""Задачи: создание клиентом, жизненный цикл, комментарии. Доступ по ролям."""
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from blueprints.auth import role_required
from constants import (
    NOTIF_NEW_COMMENT,
    NOTIF_NEW_TASK,
    PRIORITIES,
    PRIORITY_MEDIUM,
    ROLE_ADMIN,
    ROLE_CLIENT,
    ROLE_METHODOLOGIST,
    STATUS_ESTIMATE_PENDING,
    WORK_OTHER,
    WORK_TYPES,
)
from extensions import db
from models import ClientOrg, Comment, Task, User
from services.budgets import remaining_hours
from services.notifications import notify
from services.tasks import ACTIONS, TransitionError, apply_action, available_actions

tasks_bp = Blueprint("tasks", __name__, url_prefix="/tasks")


# --------------------------------------------------------------------------- #
# Доступ
# --------------------------------------------------------------------------- #
def _load_task_or_403(task_id) -> Task:
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    if current_user.is_admin:
        return task
    if current_user.is_methodologist:
        if task.client is None or task.client.methodologist_id != current_user.id:
            abort(403)
        return task
    if current_user.is_client:
        if task.client_id != current_user.client_id:
            abort(403)
        return task
    abort(403)


def _can_comment(task) -> bool:
    if current_user.is_admin:
        return True
    if current_user.is_methodologist:
        return task.client and task.client.methodologist_id == current_user.id
    if current_user.is_client:
        return task.client_id == current_user.client_id
    return False


# --------------------------------------------------------------------------- #
# Список задач (роль-зависимый)
# --------------------------------------------------------------------------- #
@tasks_bp.route("/")
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST, ROLE_CLIENT)
def list_tasks():
    query = Task.query

    if current_user.is_client:
        query = query.filter(Task.client_id == current_user.client_id)
    elif current_user.is_methodologist:
        query = query.join(ClientOrg, Task.client_id == ClientOrg.id).filter(
            ClientOrg.methodologist_id == current_user.id
        )
    # admin — все задачи

    tasks = query.order_by(Task.updated_at.desc()).all()

    # Имена постановщиков и клиентов для строк.
    author_ids = {t.created_by for t in tasks if t.created_by}
    authors = {
        u.id: u.full_name for u in User.query.filter(User.id.in_(author_ids)).all()
    } if author_ids else {}

    show_client_col = current_user.is_admin or current_user.is_methodologist

    return render_template(
        "tasks/list.html",
        tasks=tasks,
        authors=authors,
        show_client_col=show_client_col,
    )


# --------------------------------------------------------------------------- #
# Создание задачи (клиент)
# --------------------------------------------------------------------------- #
@tasks_bp.route("/new", methods=["GET", "POST"])
@role_required(ROLE_CLIENT)
def new_task():
    if current_user.client_id is None:
        abort(403)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        priority = request.form.get("priority") or PRIORITY_MEDIUM
        work_type = request.form.get("work_type") or WORK_OTHER

        if not title or not description:
            flash("Название и описание обязательны.", "error")
        elif priority not in PRIORITIES or work_type not in WORK_TYPES:
            flash("Некорректный приоритет или тип работ.", "error")
        else:
            task = Task(
                client_id=current_user.client_id,
                created_by=current_user.id,
                title=title,
                description=description,
                priority=priority,
                work_type=work_type,
                actual_hours=0,
            )
            db.session.add(task)
            db.session.commit()

            org = db.session.get(ClientOrg, current_user.client_id)
            if org and org.methodologist_id:
                notify(
                    org.methodologist_id,
                    NOTIF_NEW_TASK,
                    f"Новая задача от {org.name} / {current_user.full_name}: «{title}».",
                    task_id=task.id,
                )
            flash("Задача создана.", "info")
            return redirect(url_for("tasks.task_detail", task_id=task.id))

    return render_template("tasks/create.html", priorities=PRIORITIES, work_types=WORK_TYPES)


# --------------------------------------------------------------------------- #
# Карточка задачи
# --------------------------------------------------------------------------- #
@tasks_bp.route("/<int:task_id>")
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST, ROLE_CLIENT)
def task_detail(task_id):
    task = _load_task_or_403(task_id)

    comments = (
        Comment.query.filter_by(task_id=task.id)
        .order_by(Comment.created_at.asc())
        .all()
    )
    author_ids = {c.author_id for c in comments if c.author_id}
    authors = {
        u.id: u for u in User.query.filter(User.id.in_(author_ids)).all()
    } if author_ids else {}

    actions = available_actions(task, current_user)

    # Предупреждение о превышении лимита для клиента на этапе подтверждения оценки.
    limit_warning = None
    if current_user.is_client and task.status == STATUS_ESTIMATE_PENDING and task.estimated_hours:
        today = date.today()
        remaining = remaining_hours(task.client_id, today.year, today.month)
        if Decimal(str(task.estimated_hours)) > remaining:
            over = Decimal(str(task.estimated_hours)) - remaining
            limit_warning = f"Эта задача выведет вас за лимит месяца на {over} ч."

    return render_template(
        "tasks/detail.html",
        task=task,
        comments=comments,
        comment_authors=authors,
        actions=actions,
        can_comment=_can_comment(task),
        limit_warning=limit_warning,
        author=db.session.get(User, task.created_by) if task.created_by else None,
        is_staff=current_user.is_admin or current_user.is_methodologist,
    )


# --------------------------------------------------------------------------- #
# Переход по матрице
# --------------------------------------------------------------------------- #
@tasks_bp.route("/<int:task_id>/transition", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST, ROLE_CLIENT)
def transition(task_id):
    task = _load_task_or_403(task_id)
    action_key = request.form.get("action")

    # Колбэки для побочных эффектов.
    def _add_comment(body):
        db.session.add(
            Comment(task_id=task.id, author_id=current_user.id, body=body)
        )

    def _notify_client(ntype, body):
        # Уведомляем постановщика задачи (сотрудника клиента).
        if task.created_by:
            notify(task.created_by, ntype, body, task_id=task.id)

    def _notify_staff(ntype, body):
        org = task.client
        if org and org.methodologist_id:
            notify(org.methodologist_id, ntype, body, task_id=task.id)

    try:
        message = apply_action(
            task,
            current_user,
            action_key,
            request.form,
            add_comment=_add_comment,
            notify_client=_notify_client,
            notify_staff=_notify_staff,
        )
        db.session.commit()
        flash(message, "info")
    except TransitionError as exc:
        db.session.rollback()
        if str(exc) == "__forbidden__":
            abort(403)
        flash(str(exc), "error")

    return redirect(url_for("tasks.task_detail", task_id=task.id))


# --------------------------------------------------------------------------- #
# Правка оценки вне пайплайна (методолог/админ, любой статус)
# --------------------------------------------------------------------------- #
@tasks_bp.route("/<int:task_id>/estimate", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def edit_estimate(task_id):
    task = _load_task_or_403(task_id)
    raw = request.form.get("estimated_hours")
    try:
        if raw is None or str(raw).strip() == "":
            raise ValueError("Укажите оценку часов.")
        hours = Decimal(str(raw).replace(",", ".").strip())
        if hours < 0:
            raise ValueError("Оценка не может быть отрицательной.")
    except (InvalidOperation, ValueError) as exc:
        flash(str(exc) if isinstance(exc, ValueError) else "Некорректное число.", "error")
        return redirect(url_for("tasks.task_detail", task_id=task.id))

    task.estimated_hours = hours
    db.session.commit()
    flash("Оценка обновлена.", "info")
    return redirect(url_for("tasks.task_detail", task_id=task.id))


# --------------------------------------------------------------------------- #
# Комментарий
# --------------------------------------------------------------------------- #
@tasks_bp.route("/<int:task_id>/comment", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST, ROLE_CLIENT)
def add_comment(task_id):
    task = _load_task_or_403(task_id)
    if not _can_comment(task):
        abort(403)

    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Комментарий не может быть пустым.", "error")
        return redirect(url_for("tasks.task_detail", task_id=task.id))

    db.session.add(Comment(task_id=task.id, author_id=current_user.id, body=body))
    db.session.commit()

    # Уведомление противоположной стороне.
    org = task.client
    if current_user.is_client:
        if org and org.methodologist_id:
            notify(
                org.methodologist_id,
                NOTIF_NEW_COMMENT,
                f"Новый комментарий по задаче «{task.title}» от {current_user.full_name}.",
                task_id=task.id,
            )
    else:
        # Методолог/админ пишет — уведомляем постановщика.
        if task.created_by and task.created_by != current_user.id:
            notify(
                task.created_by,
                NOTIF_NEW_COMMENT,
                f"Новый комментарий по задаче «{task.title}».",
                task_id=task.id,
            )

    flash("Комментарий добавлен.", "info")
    return redirect(url_for("tasks.task_detail", task_id=task.id))
