"""Расширения Flask: инициализируются в app factory."""
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Требуется вход."


@login_manager.user_loader
def load_user(user_id):
    # Импорт внутри функции, чтобы избежать циклического импорта models <-> extensions.
    from models import User

    return db.session.get(User, int(user_id))
