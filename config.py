"""Конфигурация приложения: чтение env, настройки Flask/SQLAlchemy."""
import os

from dotenv import load_dotenv

load_dotenv()  # локальная разработка через .env; на Railway env приходят из окружения

# Актуальную строку модели Sonnet подтвердить перед релизом стадий 8 (AI-отчёт).
# Значение можно переопределить через env ANTHROPIC_MODEL.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"  # подтвердить актуальность


def _normalize_database_url(url: str) -> str:
    """Railway отдаёт DATABASE_URL со схемой postgres:// — SQLAlchemy 2.x требует postgresql://."""
    if not url:
        return url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    # БД: на Railway DATABASE_URL — внутренняя reference-переменная PostgreSQL.
    # Для локального запуска без Postgres падаем на sqlite, чтобы каркас поднимался.
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(
        os.environ.get("DATABASE_URL", "sqlite:///sg_tdmanager.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # AI (используется со стадии 8) — код не должен падать при отсутствии ключа.
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)

    # Telegram (стадия 7) — опционален на старте.
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    # Сид первого админа (стадия 1).
    ADMIN_LOGIN = os.environ.get("ADMIN_LOGIN", "")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

    # Фрод-монитор (стадия 6).
    try:
        FRAUD_DAILY_HOURS_THRESHOLD = int(os.environ.get("FRAUD_DAILY_HOURS_THRESHOLD", "8"))
    except (TypeError, ValueError):
        FRAUD_DAILY_HOURS_THRESHOLD = 8
