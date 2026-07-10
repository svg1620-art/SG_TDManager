"""Идемпотентный сид первого администратора из ADMIN_LOGIN/ADMIN_PASSWORD."""
import logging

from constants import ROLE_ADMIN
from extensions import db
from models import User

logger = logging.getLogger(__name__)


def seed_admin(app) -> None:
    """Создаёт первого админа, если ни одного пользователя-админа ещё нет.

    Идемпотентно: повторный запуск не создаёт дублей.
    """
    login = (app.config.get("ADMIN_LOGIN") or "").strip()
    password = app.config.get("ADMIN_PASSWORD") or ""

    if not login or not password:
        logger.warning(
            "ADMIN_LOGIN/ADMIN_PASSWORD не заданы — сид админа пропущен."
        )
        return

    existing_admin = User.query.filter_by(role=ROLE_ADMIN).first()
    if existing_admin is not None:
        logger.info("Админ уже существует — сид пропущен.")
        return

    # Защита от коллизии логина с уже существующим пользователем иной роли.
    if User.query.filter_by(login=login).first() is not None:
        logger.warning(
            "Пользователь с логином %s уже существует — сид админа пропущен.", login
        )
        return

    admin = User(role=ROLE_ADMIN, full_name="Администратор", login=login)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    logger.info("Создан первый админ с логином %s.", login)
