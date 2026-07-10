"""Справочники и enum-подобные строковые константы (переиспользуются во всех стадиях)."""

# --- Роли пользователей ---
ROLE_ADMIN = "admin"
ROLE_METHODOLOGIST = "methodologist"
ROLE_CLIENT = "client"

ROLES = (ROLE_ADMIN, ROLE_METHODOLOGIST, ROLE_CLIENT)

ROLE_LABELS = {
    ROLE_ADMIN: "Администратор",
    ROLE_METHODOLOGIST: "Методолог",
    ROLE_CLIENT: "Клиент",
}

# --- Статусы задач (жизненный цикл) ---
STATUS_NEW = "new"
STATUS_ESTIMATE_PENDING = "estimate_pending"
STATUS_APPROVED = "approved"
STATUS_IN_PROGRESS = "in_progress"
STATUS_CLARIFICATION = "clarification"
STATUS_DONE = "done"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"

TASK_STATUSES = (
    STATUS_NEW,
    STATUS_ESTIMATE_PENDING,
    STATUS_APPROVED,
    STATUS_IN_PROGRESS,
    STATUS_CLARIFICATION,
    STATUS_DONE,
    STATUS_ACCEPTED,
    STATUS_REJECTED,
)

STATUS_LABELS = {
    STATUS_NEW: "Новая",
    STATUS_ESTIMATE_PENDING: "Ожидает подтверждения",
    STATUS_APPROVED: "Готова к работе",
    STATUS_IN_PROGRESS: "В работе",
    STATUS_CLARIFICATION: "На уточнении",
    STATUS_DONE: "Выполнена",
    STATUS_ACCEPTED: "Принята",
    STATUS_REJECTED: "Отклонена",
}

# --- Приоритеты ---
PRIORITY_LOW = "low"
PRIORITY_MEDIUM = "medium"
PRIORITY_HIGH = "high"
PRIORITY_URGENT = "urgent"

PRIORITIES = (PRIORITY_LOW, PRIORITY_MEDIUM, PRIORITY_HIGH, PRIORITY_URGENT)

PRIORITY_LABELS = {
    PRIORITY_LOW: "Низкий",
    PRIORITY_MEDIUM: "Средний",
    PRIORITY_HIGH: "Высокий",
    PRIORITY_URGENT: "Срочный",
}

# --- Типы работ ---
WORK_CONTENT = "content"
WORK_SETUP = "setup"
WORK_COMMUNICATION = "communication"
WORK_PLATFORM = "platform"
WORK_ATTESTATION = "attestation"
WORK_REPORTS = "reports"
WORK_OTHER = "other"

WORK_TYPES = (
    WORK_CONTENT,
    WORK_SETUP,
    WORK_COMMUNICATION,
    WORK_PLATFORM,
    WORK_ATTESTATION,
    WORK_REPORTS,
    WORK_OTHER,
)

WORK_TYPE_LABELS = {
    WORK_CONTENT: "Контент",
    WORK_SETUP: "Настройка",
    WORK_COMMUNICATION: "Коммуникация",
    WORK_PLATFORM: "Работа с платформой",
    WORK_ATTESTATION: "Аттестации",
    WORK_REPORTS: "Отчёты",
    WORK_OTHER: "Прочее",
}

# --- Источник месячного отчёта ---
REPORT_SOURCE_AUTO = "auto"
REPORT_SOURCE_MANUAL = "manual"
