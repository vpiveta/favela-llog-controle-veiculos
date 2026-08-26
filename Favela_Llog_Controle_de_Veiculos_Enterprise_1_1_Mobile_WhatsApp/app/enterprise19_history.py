from decimal import Decimal

from flask import render_template, request
from flask_login import current_user, login_required
from sqlalchemy import or_

from .models import Expense


def _history_view():
    from .routes import car_plate_photo_ids
    q = Expense.query.filter_by(is_deleted=False)
    if not current_user.is_admin:
        q = q.filter(or_(
            Expense.created_by_id == current_user.id,
            Expense.responsible_driver_id == current_user.id,
        ))
    kind = request.args.get('type')
    if kind:
        q = q.filter_by(expense_type=kind)
    expenses = q.order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    motorcycle_expenses = [e for e in expenses if e.asset_type == 'MOTORCYCLE']
    car_expenses = [e for e in expenses if e.asset_type == 'CAR']
    return render_template(
        'driver/history.html',
        motorcycle_expenses=motorcycle_expenses,
        car_expenses=car_expenses,
        motorcycle_total=sum((Decimal(e.amount) for e in motorcycle_expenses), Decimal('0')),
        car_total=sum((Decimal(e.amount) for e in car_expenses), Decimal('0')),
        car_plate_photo_ids=car_plate_photo_ids(car_expenses),
        selected_asset_type=request.args.get('asset_type','').upper(),
    )


def init_enterprise19_history(app):
    app.view_functions['main.history'] = login_required(_history_view)
