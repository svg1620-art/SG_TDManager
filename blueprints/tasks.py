"""Задачи: создание клиентом, жизненный цикл, комментарии, трекинг времени."""
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
    STATUS_ACCEPTED,
    STATUS_APPROVED,
    STATUS_CLARIFICATION,
    STATUS_DONE,
    STATUS_ESTIMATE_PENDING,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    STATUS_REJECTED,
    TASK_STATUSES,
    WORK_OTHER,
    WORK_TYPES,
)
from extensions import db
from models import ClientOrg, Comment, Task, TimeEntry, User
from services.budgets import consumed_hours, effective_limit, remaining_hours
from services.notifications import notify
from services.tasks import ACTIONS, TransitionError, apply_action, available_actions
from services.time_entries import recalc_task_actual

tasks_bp = Blueprint("tasks", __name__, url_prefix="/tasks")

# Статусы, по которым можно списывать время (задача взята в работу или прошла её).
LOGGABLE_STATUSES = {
    STATUS_IN_PROGRESS,
    STATUS_CLARIFICATION,
    STATUS_DONE,
    STATUS_ACCEPTED,
}
MAX_HOURS_PER_ENTRY = Decimal("24")


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


def _load_task_staff_or_403(task_id) -> Task:
    """Загрузить задачу для операций трекинга: только методолог-владелец или админ."""
    task = _load_task_or_403(task_id)  # 403, если методолог не владелец клиента
    if not (current_user.is_admin or current_user.is_methodologist):
        abort(403)
    return task


def _parse_hours(raw):
    if raw is None or str(raw).strip() == "":
        raise ValueError("Укажите часы (например, 1.5).")
    try:
        hours = Decimal(str(raw).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        raise ValueError("Часы должны быть числом (например, 1.5).")
    if hours <= 0:
        raise ValueError("Часы должны быть больше нуля.")
    if hours > MAX_HOURS_PER_ENTRY:
        raise ValueError("Слишком много часов в одной записи (максимум 24).")
    return hours


def _parse_work_date(raw):
    if not raw:
        return date.today()
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        raise ValueError("Некорректная дата.")
    if d > date.today():
        raise ValueError("Дата не может быть в будущем.")
    return d


def _maybe_notify_minus(task, year, month, remaining_before):
    """Если после списания остаток месяца впервые ушёл в минус — уведомить методолога."""
    remaining_after = remaining_hours(task.client_id, year, month)
    if remaining_before >= 0 and remaining_after < 0:
        org = task.client
        if org and org.methodologist_id:
            over = -remaining_after
            notify(
                org.methodologist_id,
                "budget_minus",
                f"Клиент {org.name} ушёл в минус по лимиту {month:02d}.{year} на {over} ч.",
                task_id=task.id,
            )


# --------------------------------------------------------------------------- #
# Список задач (роль-зависимый)
# --------------------------------------------------------------------------- #
def _staff_client_options():
    """Клиенты для фильтра: свои — методологу, все — админу."""
    q = ClientOrg.query
    if current_user.is_methodologist:
        q = q.filter_by(methodologist_id=current_user.id)
    return q.order_by(ClientOrg.name).all()


def _scoped_task_query():
    """Базовая выборка задач по роли (клиент/методолог/админ)."""
    query = Task.query
    if current_user.is_client:
        query = query.filter(Task.client_id == current_user.client_id)
    elif current_user.is_methodologist:
        query = query.join(ClientOrg, Task.client_id == ClientOrg.id).filter(
            ClientOrg.methodologist_id == current_user.id
        )
    return query


def _apply_filters(query):
    """Наложить фильтры из query-параметров. Возвращает (query, active_filters)."""
    filters = {
        "client_id": request.args.get("client_id", type=int),
        "status": request.args.get("status") or None,
        "priority": request.args.get("priority") or None,
        "work_type": request.args.get("work_type") or None,
    }
    if filters["client_id"]:
        query = query.filter(Task.client_id == filters["client_id"])
    if filters["status"] in TASK_STATUSES:
        query = query.filter(Task.status == filters["status"])
    if filters["priority"] in PRIORITIES:
        query = query.filter(Task.priority == filters["priority"])
    if filters["work_type"] in WORK_TYPES:
        query = query.filter(Task.work_type == filters["work_type"])
    return query, filters


def _authors_map(tasks):
    author_ids = {t.created_by for t in tasks if t.created_by}
    if not author_ids:
        return {}
    return {u.id: u.full_name for u in User.query.filter(User.id.in_(author_ids)).all()}


@tasks_bp.route("/")
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST, ROLE_CLIENT)
def list_tasks():
    query, filters = _apply_filters(_scoped_task_query())
    tasks = query.order_by(Task.updated_at.desc()).all()
    authors = _authors_map(tasks)

    is_staff = current_user.is_admin or current_user.is_methodologist

    # Короткая строка «Лимит / Расход / Остаток» за текущий месяц для клиента.
    month_summary = None
    if current_user.is_client and current_user.client_id:
        today = date.today()
        eff = effective_limit(current_user.client_id, today.year, today.month)
        cons = consumed_hours(current_user.client_id, today.year, today.month)
        month_summary = {
            "year": today.year,
            "month": today.month,
            "effective": eff,
            "consumed": cons,
            "remaining": eff - cons,
        }

    return render_template(
        "tasks/list.html",
        tasks=tasks,
        authors=authors,
        show_client_col=is_staff,
        month_summary=month_summary,
        is_staff=is_staff,
        filters=filters,
        client_options=_staff_client_options() if is_staff else [],
        priorities=PRIORITIES,
        work_types=WORK_TYPES,
        statuses=TASK_STATUSES,
    )


# --------------------------------------------------------------------------- #
# Доска задач (методолог/админ): колонки-статусы + действия по матрице
# --------------------------------------------------------------------------- #
@tasks_bp.route("/board")
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def board():
    query, filters = _apply_filters(_scoped_task_query())
    tasks = query.order_by(Task.updated_at.desc()).all()
    authors = _authors_map(tasks)

    columns = [
        STATUS_NEW,
        STATUS_ESTIMATE_PENDING,
        STATUS_APPROVED,
        STATUS_IN_PROGRESS,
        STATUS_CLARIFICATION,
        STATUS_DONE,
        STATUS_ACCEPTED,
        STATUS_REJECTED,
    ]
    grouped = {s: [] for s in columns}
    for t in tasks:
        grouped.setdefault(t.status, []).append(t)

    # Доступные действия по каждой задаче — из матрицы Стадии 3 (не дублируем правила).
    actions_by_task = {t.id: available_actions(t, current_user) for t in tasks}

    next_url = url_for("tasks.board", **{k: v for k, v in filters.items() if v})

    return render_template(
        "tasks/board.html",
        columns=columns,
        grouped=grouped,
        authors=authors,
        actions_by_task=actions_by_task,
        next_url=next_url,
        filters=filters,
        client_options=_staff_client_options(),
        priorities=PRIORITIES,
        work_types=WORK_TYPES,
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
    today = date.today()

    # Предупреждение о превышении лимита для клиента на этапе подтверждения оценки.
    limit_warning = None
    if current_user.is_client and task.status == STATUS_ESTIMATE_PENDING and task.estimated_hours:
        remaining = remaining_hours(task.client_id, today.year, today.month)
        if Decimal(str(task.estimated_hours)) > remaining:
            over = Decimal(str(task.estimated_hours)) - remaining
            limit_warning = f"Эта задача выведет вас за лимит месяца на {over} ч."

    is_staff = current_user.is_admin or current_user.is_methodologist

    # Записи времени + исполнители (ФИО важно: клиент мог быть передан другому методологу).
    time_entries = (
        TimeEntry.query.filter_by(task_id=task.id)
        .order_by(TimeEntry.work_date.desc(), TimeEntry.created_at.desc())
        .all()
    )
    logger_ids = {e.methodologist_id for e in time_entries if e.methodologist_id}
    loggers = {
        u.id: u.full_name for u in User.query.filter(User.id.in_(logger_ids)).all()
    } if logger_ids else {}

    # Блок лимита текущего месяца клиента (для методолога/админа).
    month_limit = None
    if is_staff:
        eff = effective_limit(task.client_id, today.year, today.month)
        cons = consumed_hours(task.client_id, today.year, today.month)
        month_limit = {
            "year": today.year,
            "month": today.month,
            "effective": eff,
            "consumed": cons,
            "remaining": eff - cons,
        }

    return render_template(
        "tasks/detail.html",
        task=task,
        comments=comments,
        comment_authors=authors,
        actions=actions,
        can_comment=_can_comment(task),
        limit_warning=limit_warning,
        author=db.session.get(User, task.created_by) if task.created_by else None,
        is_staff=is_staff,
        time_entries=time_entries,
        loggers=loggers,
        can_log=is_staff and task.status in LOGGABLE_STATUSES,
        month_limit=month_limit,
        today=today,
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

    return redirect(_safe_next(url_for("tasks.task_detail", task_id=task.id)))


def _safe_next(default_url):
    """Локальный редирект по параметру next (доска с фильтрами), иначе — default."""
    nxt = request.form.get("next")
    if nxt and nxt.startswith("/"):
        return nxt
    return default_url


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


# --------------------------------------------------------------------------- #
# Трекинг времени (методолог-владелец / админ)
# --------------------------------------------------------------------------- #
@tasks_bp.route("/<int:task_id>/time", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def add_time(task_id):
    task = _load_task_staff_or_403(task_id)

    if task.status not in LOGGABLE_STATUSES:
        flash("Время можно списывать только по задачам, взятым в работу.", "error")
        return redirect(url_for("tasks.task_detail", task_id=task.id))

    try:
        hours = _parse_hours(request.form.get("hours"))
        work_date = _parse_work_date(request.form.get("work_date"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("tasks.task_detail", task_id=task.id))

    note = (request.form.get("note") or "").strip() or None

    # Остаток месяца записи ДО списания (для сигнала о переходе в минус).
    remaining_before = remaining_hours(task.client_id, work_date.year, work_date.month)

    entry = TimeEntry(
        task_id=task.id,
        methodologist_id=current_user.id,
        hours=hours,
        work_date=work_date,
        note=note,
    )
    db.session.add(entry)
    recalc_task_actual(task.id)  # коммитит и пересчитывает кэш actual_hours

    _maybe_notify_minus(task, work_date.year, work_date.month, remaining_before)

    flash("Запись времени добавлена.", "info")
    return redirect(url_for("tasks.task_detail", task_id=task.id))


def _load_entry_staff_or_403(entry_id):
    """Запись + проверка прав: автор-методолог записи или админ; владение клиентом."""
    entry = db.session.get(TimeEntry, entry_id)
    if entry is None:
        abort(404)
    task = _load_task_staff_or_403(entry.task_id)  # владение клиентом + роль staff
    # Редактировать/удалять может автор записи или админ.
    if not current_user.is_admin and entry.methodologist_id != current_user.id:
        abort(403)
    return entry, task


@tasks_bp.route("/time/<int:entry_id>/edit", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def edit_time(entry_id):
    entry, task = _load_entry_staff_or_403(entry_id)

    try:
        hours = _parse_hours(request.form.get("hours"))
        work_date = _parse_work_date(request.form.get("work_date"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("tasks.task_detail", task_id=task.id))

    remaining_before = remaining_hours(task.client_id, work_date.year, work_date.month)

    entry.hours = hours
    entry.work_date = work_date
    entry.note = (request.form.get("note") or "").strip() or None
    recalc_task_actual(task.id)

    _maybe_notify_minus(task, work_date.year, work_date.month, remaining_before)

    flash("Запись обновлена.", "info")
    return redirect(url_for("tasks.task_detail", task_id=task.id))


@tasks_bp.route("/time/<int:entry_id>/delete", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def delete_time(entry_id):
    entry, task = _load_entry_staff_or_403(entry_id)
    db.session.delete(entry)
    db.session.commit()
    recalc_task_actual(task.id)
    flash("Запись удалена.", "info")
    return redirect(url_for("tasks.task_detail", task_id=task.id))
