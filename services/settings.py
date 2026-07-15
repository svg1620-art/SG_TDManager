"""Key-value настройки приложения (общий чат управленческого отчёта и т.п.)."""
from extensions import db
from models import AppSetting

# Ключи и значения по умолчанию.
INTERNAL_DIGEST_ENABLED = "internal_digest_enabled"
INTERNAL_DIGEST_CHAT_ID = "internal_digest_chat_id"
INTERNAL_DIGEST_HOUR = "internal_digest_hour"

DEFAULTS = {
    INTERNAL_DIGEST_ENABLED: "1",
    INTERNAL_DIGEST_CHAT_ID: "",
    INTERNAL_DIGEST_HOUR: "19",
}


def get(key, default=None):
    row = db.session.get(AppSetting, key)
    if row is not None and row.value is not None:
        return row.value
    return DEFAULTS.get(key, default)


def set(key, value):
    row = db.session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.session.add(row)
    else:
        row.value = value
    db.session.commit()


def get_int(key, default):
    try:
        return int(get(key, default))
    except (TypeError, ValueError):
        return default


def is_internal_digest_enabled() -> bool:
    return get(INTERNAL_DIGEST_ENABLED, "1") == "1"


def internal_digest_chat_id():
    return (get(INTERNAL_DIGEST_CHAT_ID, "") or "").strip()


def internal_digest_hour() -> int:
    return get_int(INTERNAL_DIGEST_HOUR, 19)
