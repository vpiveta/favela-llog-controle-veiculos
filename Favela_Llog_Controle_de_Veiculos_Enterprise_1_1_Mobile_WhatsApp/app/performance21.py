from decimal import Decimal

from flask import render_template, request
from flask_login import current_user, login_required
from sqlalchemy import case, func
from sqlalchemy.orm import selectinload

from .models import db, Expense


def fast_history():
    """Histórico paginado: não carrega toda a vida do sistema no celular."""
    from .routes import car_plate_photo_ids

    q = Expense.query.filter(Expense.is_deleted.is_(False))
    if not current_user.is_admin:
        q = q.filter(Expense.created_by_id == current_user.id)

    kind = request.args.get('type')
    if kind:
        q = q.filter(Expense.expense_type == kind)

    # Totais continuam representando TODO o filtro, mesmo exibindo só uma página.
    totals_q = db.session.query(
        func.coalesce(func.sum(case((Expense.asset_type == 'MOTORCYCLE', Expense.amount), else_=0)), 0),
        func.coalesce(func.sum(case((Expense.asset_type == 'CAR', Expense.amount), else_=0)), 0),
    ).filter(Expense.is_deleted.is_(False))
    if not current_user.is_admin:
        totals_q = totals_q.filter(Expense.created_by_id == current_user.id)
    if kind:
        totals_q = totals_q.filter(Expense.expense_type == kind)
    totals = totals_q.one()

    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = 30
    rows = q.options(
        selectinload(Expense.vehicle),
        selectinload(Expense.created_by),
        selectinload(Expense.responsible_driver),
        selectinload(Expense.maintenance),
        selectinload(Expense.fuel),
    ).order_by(Expense.expense_date.desc(), Expense.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    expenses = rows.items
    motorcycle_expenses = [e for e in expenses if e.asset_type == 'MOTORCYCLE']
    car_expenses = [e for e in expenses if e.asset_type == 'CAR']

    return render_template(
        'driver/history.html',
        motorcycle_expenses=motorcycle_expenses,
        car_expenses=car_expenses,
        motorcycle_total=Decimal(totals[0] or 0),
        car_total=Decimal(totals[1] or 0),
        car_plate_photo_ids=car_plate_photo_ids(car_expenses),
        selected_asset_type=request.args.get('asset_type', '').upper(),
        history_pagination=rows,
    )


def init_performance21(app):
    # Mantém a URL e permissões existentes; troca apenas a implementação pesada.
    app.view_functions['main.history'] = login_required(fast_history)
