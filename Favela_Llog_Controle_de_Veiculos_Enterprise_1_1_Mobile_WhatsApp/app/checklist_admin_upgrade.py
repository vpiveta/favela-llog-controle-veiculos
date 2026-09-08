from flask import request
from flask_login import current_user
from sqlalchemy.orm import selectinload

from .models import Expense


def init_checklist_admin_upgrade(app):
    @app.context_processor
    def checklist_admin_context():
        if not current_user.is_authenticated or request.endpoint != 'main.admin_checklists':
            return {'checklist_maintenance': []}
        try:
            q = Expense.query.options(
                selectinload(Expense.vehicle),
                selectinload(Expense.responsible_driver),
                selectinload(Expense.created_by),
                selectinload(Expense.maintenance),
            ).filter(
                Expense.expense_type == 'MAINTENANCE',
                Expense.asset_type == 'MOTORCYCLE',
                Expense.is_deleted.is_(False),
            )
            if not current_user.is_global_admin:
                q = q.filter(Expense.base_code == current_user.base_code)
            return {'checklist_maintenance': q.order_by(Expense.expense_date.desc(), Expense.id.desc()).limit(100).all()}
        except Exception:
            app.logger.exception('Falha ao carregar manutenções na central de checklists')
            return {'checklist_maintenance': []}
