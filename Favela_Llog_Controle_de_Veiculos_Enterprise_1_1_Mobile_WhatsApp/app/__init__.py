import os
from pathlib import Path
from flask import Flask
from flask_login import LoginManager
from dotenv import load_dotenv
from .models import db, User

login_manager = LoginManager()
login_manager.login_view = 'auth.login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def create_app():
    load_dotenv()
    app = Flask(__name__)
    root = Path(app.root_path).parent
    db_url = os.getenv('DATABASE_URL')
    if db_url and db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql+psycopg://', 1)
    elif db_url and db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+psycopg://', 1)
    app.config.update(
        SECRET_KEY=os.getenv('SECRET_KEY', 'dev-change-me'),
        SQLALCHEMY_DATABASE_URI=db_url or f"sqlite:///{root / 'instance' / 'fleet.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        UPLOAD_FOLDER=str(root / 'uploads' / 'receipts'),
    )
    (root / 'instance').mkdir(parents=True, exist_ok=True)
    Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    from .routes import main_bp, auth_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    from .cli import register_cli
    register_cli(app)
    with app.app_context():
        db.create_all()
        # Migrações leves e idempotentes para bancos já existentes.
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            migrations = {
                'alert_recipient': [('phone', 'VARCHAR(30)')],
                'expense': [('is_deleted','BOOLEAN NOT NULL DEFAULT FALSE'),('deleted_at','TIMESTAMP'),('deleted_by_id','INTEGER'),('deletion_reason','TEXT')],
                'daily_checklist': [('is_deleted','BOOLEAN NOT NULL DEFAULT FALSE'),('deleted_at','TIMESTAMP'),('deleted_by_id','INTEGER'),('deletion_reason','TEXT')],
                'admin_notification': [('whatsapp_sent_at','TIMESTAMP'),('whatsapp_sent_by_id','INTEGER')],
            }
            for table, fields in migrations.items():
                existing = {c['name'] for c in inspector.get_columns(table)}
                for field, sqltype in fields:
                    if field not in existing:
                        db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN {field} {sqltype}'))
            db.session.commit()
        except Exception:
            db.session.rollback()
    return app
