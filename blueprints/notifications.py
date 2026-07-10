"""Колокольчик: переход к задаче с отметкой прочтения и «прочитать все»."""
from flask import Blueprint, redirect, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Notification
from services.notifications import mark_all_read, mark_read

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")


def _safe_back(default_endpoint="auth.index"):
    ref = request.referrer
    if ref and ref.startswith(request.host_url):
        return ref
    return url_for(default_endpoint)


@notifications_bp.route("/<int:notification_id>/go")
@login_required
def go(notification_id):
    """Отметить уведомление прочитанным и перейти к связанной задаче."""
    n = db.session.get(Notification, notification_id)
    if n is None or n.user_id != current_user.id:
        return redirect(url_for("auth.index"))
    mark_read(notification_id, current_user.id)
    if n.task_id:
        return redirect(url_for("tasks.task_detail", task_id=n.task_id))
    return redirect(url_for("auth.index"))


@notifications_bp.route("/<int:notification_id>/read", methods=["POST"])
@login_required
def read_one(notification_id):
    mark_read(notification_id, current_user.id)
    return redirect(_safe_back())


@notifications_bp.route("/read-all", methods=["POST"])
@login_required
def read_all():
    mark_all_read(current_user.id)
    return redirect(_safe_back())
