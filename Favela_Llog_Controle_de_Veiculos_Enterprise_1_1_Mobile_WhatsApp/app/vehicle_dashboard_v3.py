from datetime import timedelta

from flask import flash, redirect, request, url_for
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from .models import db, DailyChecklist, Expense, Vehicle
from .time_utils import local_today


def _active_or_owned_vehicle():
    if not current_user.is_authenticated or current_user.is_admin:
        return None
    try:
        from .enterprise19 import active_vehicle
        vehicle = active_vehicle()
        if vehicle:
            return vehicle
    except Exception:
        pass
    return current_user.vehicle if current_user.vehicle and current_user.vehicle.vehicle_type == 'MOTORCYCLE' else None


def _last_return(vehicle_id):
    if not vehicle_id:
        return None
    return DailyChecklist.query.options(selectinload(DailyChecklist.driver),selectinload(DailyChecklist.vehicle)).filter_by(vehicle_id=vehicle_id,checklist_type='DEVOLUCAO',is_deleted=False).order_by(DailyChecklist.checklist_date.desc(),DailyChecklist.created_at.desc(),DailyChecklist.id.desc()).first()


def _last_fuel(vehicle_id):
    if not vehicle_id:
        return None
    return Expense.query.options(selectinload(Expense.created_by),selectinload(Expense.vehicle)).filter_by(vehicle_id=vehicle_id,expense_type='FUEL',is_deleted=False).order_by(Expense.expense_date.desc(),Expense.id.desc()).first()


def _fuel_age(expense):
    if not expense or not expense.expense_date:
        return None
    return max(0, (local_today() - expense.expense_date).days)


def _owner_borrow_alert():
    if not current_user.is_authenticated or current_user.role != 'DRIVER' or not current_user.vehicle:
        return None
    yesterday = local_today() - timedelta(days=1)
    return DailyChecklist.query.options(selectinload(DailyChecklist.driver),selectinload(DailyChecklist.vehicle)).filter(DailyChecklist.owner_driver_id == current_user.id,DailyChecklist.vehicle_id == current_user.vehicle.id,DailyChecklist.driver_id != current_user.id,DailyChecklist.borrowed_vehicle.is_(True),DailyChecklist.checklist_date == yesterday,DailyChecklist.is_deleted.is_(False)).order_by((DailyChecklist.checklist_type == 'DEVOLUCAO').desc(),DailyChecklist.created_at.desc(),DailyChecklist.id.desc()).first()


def _fleet_fuel_status():
    if not current_user.is_authenticated or not current_user.is_admin:
        return []
    vehicles = Vehicle.query.options(selectinload(Vehicle.driver)).filter_by(vehicle_type='MOTORCYCLE').order_by(Vehicle.plate).all()
    if not vehicles:
        return []
    ids = [v.id for v in vehicles]
    max_dates = db.session.query(Expense.vehicle_id.label('vehicle_id'),func.max(Expense.expense_date).label('max_date')).filter(Expense.vehicle_id.in_(ids),Expense.expense_type == 'FUEL',Expense.is_deleted.is_(False)).group_by(Expense.vehicle_id).subquery()
    rows = Expense.query.options(selectinload(Expense.created_by),selectinload(Expense.vehicle)).join(max_dates,(Expense.vehicle_id == max_dates.c.vehicle_id) & (Expense.expense_date == max_dates.c.max_date)).filter(Expense.is_deleted.is_(False),Expense.expense_type == 'FUEL').order_by(Expense.id.desc()).all()
    latest = {}
    for row in rows:
        latest.setdefault(row.vehicle_id, row)
    return [{'vehicle': vehicle,'fuel': latest.get(vehicle.id),'days': _fuel_age(latest.get(vehicle.id))} for vehicle in vehicles]


def vehicle_v3_context():
    if not current_user.is_authenticated:
        return {}
    vehicle = _active_or_owned_vehicle()
    last_return = _last_return(vehicle.id) if vehicle else None
    last_fuel = _last_fuel(vehicle.id) if vehicle else None
    return {'v3_vehicle': vehicle,'v3_last_return': last_return,'v3_last_return_km': last_return.odometer if last_return else (vehicle.current_km if vehicle else None),'v3_last_fuel': last_fuel,'v3_fuel_days': _fuel_age(last_fuel),'v3_borrow_alert': _owner_borrow_alert(),'v3_fleet_fuel': _fleet_fuel_status() if request.endpoint == 'main.dashboard' else []}


def init_vehicle_dashboard_v3(app):
    app.context_processor(vehicle_v3_context)

    @app.before_request
    def validate_checklist_odometer_against_last_return():
        if request.endpoint != 'main.checklist_new' or request.method != 'POST':
            return None
        vehicle_id = request.form.get('vehicle_id', type=int)
        odometer = request.form.get('odometer', type=int)
        if not vehicle_id or odometer is None:
            return None
        last_return = _last_return(vehicle_id)
        if last_return and odometer < last_return.odometer:
            flash(f'O KM informado ({odometer}) não pode ser menor que a última devolução ({last_return.odometer} km em {last_return.checklist_date.strftime("%d/%m/%Y")}).','danger')
            checklist_type = (request.form.get('checklist_type') or 'RETIRADA').upper()
            return redirect(url_for('main.checklist_new', type=checklist_type))
        return None

    @app.after_request
    def inject_v3_dark_theme(response):
        if response.mimetype != 'text/html':
            return response
        try:
            html = response.get_data(as_text=True)
            tags = []
            for css in ('vehicle-dashboard-v3.css','official-ui-v4.css','official-ui-v5.css'):
                if css not in html:
                    tags.append(f'<link rel="stylesheet" href="/static/css/{css}">')
            if tags and '</head>' in html:
                html = html.replace('</head>', ''.join(tags) + '</head>', 1)
                response.set_data(html)
            return response
        except Exception:
            return response
