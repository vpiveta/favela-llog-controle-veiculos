import os
from pathlib import Path
from flask import Flask
from flask_login import LoginManager
from dotenv import load_dotenv
from .models import db, User
from .time_utils import format_local_datetime

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
        APP_TIMEZONE=os.getenv('APP_TIMEZONE', 'America/Sao_Paulo'),
    )
    app.jinja_env.filters['local_dt'] = format_local_datetime
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
                'vehicle': [('vehicle_type', "VARCHAR(20) NOT NULL DEFAULT 'MOTORCYCLE'")],
                'expense': [
                    ('asset_type', "VARCHAR(20) NOT NULL DEFAULT 'MOTORCYCLE'"),
                    ('authorized_by_id','INTEGER'),
                    ('is_deleted','BOOLEAN NOT NULL DEFAULT FALSE'),('deleted_at','TIMESTAMP'),
                    ('deleted_by_id','INTEGER'),('deletion_reason','TEXT'),
                ],
                'maintenance_detail': [
                    ('is_oil_change','BOOLEAN NOT NULL DEFAULT FALSE'),
                    ('oil_amount','NUMERIC(12,2)'),
                ],
                'daily_checklist': [
                    ('odometer','INTEGER NOT NULL DEFAULT 0'),
                    ('checklist_type',"VARCHAR(20) NOT NULL DEFAULT 'RETIRADA'"),
                    ('charger_ok','BOOLEAN NOT NULL DEFAULT TRUE'),
                    ('phone_holder_ok','BOOLEAN NOT NULL DEFAULT TRUE'),
                    ('top_case_ok','BOOLEAN NOT NULL DEFAULT TRUE'),
                    ('saddlebags_ok','BOOLEAN NOT NULL DEFAULT TRUE'),
                    ('is_deleted','BOOLEAN NOT NULL DEFAULT FALSE'),
                    ('deleted_at','TIMESTAMP'),('deleted_by_id','INTEGER'),('deletion_reason','TEXT'),
                ],
                'admin_notification': [('whatsapp_sent_at','TIMESTAMP'),('whatsapp_sent_by_id','INTEGER')],
                'stored_file': [('storage_bucket','VARCHAR(120)'),('storage_path','VARCHAR(600)'),('storage_migrated_at','TIMESTAMP')],
            }
            for table, fields in migrations.items():
                existing = {c['name'] for c in inspector.get_columns(table)}
                for field, sqltype in fields:
                    if field not in existing:
                        db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN {field} {sqltype}'))
                        if table == 'daily_checklist' and field == 'checklist_type':
                            # Registros anteriores à versão 1.6 são históricos e não
                            # podem ativar, por engano, uma moto emprestada antiga.
                            db.session.execute(text("UPDATE daily_checklist SET checklist_type = 'LEGACY'"))
            # Normalização segura: itens anteriores eram motos e continuam como
            # motos. Custos antigos de óleo não são inventados nem reclassificados.
            db.session.execute(text("UPDATE vehicle SET vehicle_type = 'MOTORCYCLE' WHERE vehicle_type IS NULL OR vehicle_type = ''"))
            db.session.execute(text("UPDATE expense SET asset_type = 'MOTORCYCLE' WHERE asset_type IS NULL OR asset_type = ''"))
            db.session.commit()
        except Exception:
            db.session.rollback()
    return app
