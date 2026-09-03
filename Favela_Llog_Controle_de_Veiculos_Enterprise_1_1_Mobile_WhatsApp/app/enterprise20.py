from datetime import date
from decimal import Decimal

from flask import Blueprint, abort, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import func

from .models import db, Expense, Vehicle, DailyChecklist
from .time_utils import local_today
from .enterprise18 import BASES, is_global_admin, current_base

enterprise20_bp = Blueprint('enterprise20', __name__, url_prefix='/executive')


def _month_bounds(raw=None):
    today = local_today()
    raw = (raw or '').strip()
    try:
        year, month = [int(x) for x in raw.split('-', 1)]
        start = date(year, month, 1)
    except Exception:
        start = date(today.year, today.month, 1)
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    if start.month == 1:
        prev = date(start.year - 1, 12, 1)
    else:
        prev = date(start.year, start.month - 1, 1)
    return start, end, prev


def _selected_base():
    if is_global_admin():
        raw = (request.args.get('base') or 'ALL').upper().strip()
        return raw if raw in BASES else 'ALL'
    return current_base() or 'SDA9'


def _expense_query(start, end, base_code=None):
    q = Expense.query.filter(
        Expense.expense_date >= start,
        Expense.expense_date < end,
        Expense.is_deleted.is_(False),
    )
    if base_code and base_code != 'ALL':
        q = q.filter(Expense.base_code == base_code)
    if not current_user.is_admin:
        q = q.filter(Expense.created_by_id == current_user.id)
    return q


def _vehicle_query(base_code=None):
    q = Vehicle.query
    if base_code and base_code != 'ALL':
        q = q.filter(Vehicle.base_code == base_code)
    if not current_user.is_admin:
        if current_user.vehicle:
            q = q.filter(Vehicle.id == current_user.vehicle.id)
        else:
            q = q.filter(Vehicle.id == -1)
    return q


def _money_sum(rows, predicate=lambda e: True):
    return sum((Decimal(e.amount) for e in rows if predicate(e)), Decimal('0'))


def _month_label(start):
    names = ('Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro')
    return f'{names[start.month-1]} {start.year}'


def dashboard_v2():
    start, end, prev_start = _month_bounds(request.args.get('month'))
    base_code = _selected_base()
    current_rows = _expense_query(start, end, base_code).order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    previous_rows = _expense_query(prev_start, start, base_code).all()

    total = _money_sum(current_rows)
    previous_total = _money_sum(previous_rows)
    fuel = _money_sum(current_rows, lambda e: e.expense_type == 'FUEL')
    maintenance = _money_sum(current_rows, lambda e: e.expense_type == 'MAINTENANCE')
    motorcycle = _money_sum(current_rows, lambda e: e.asset_type == 'MOTORCYCLE')
    car = _money_sum(current_rows, lambda e: e.asset_type == 'CAR')
    delta = None
    if previous_total > 0:
        delta = ((total - previous_total) / previous_total * Decimal('100')).quantize(Decimal('0.1'))

    vehicles = _vehicle_query(base_code).order_by(Vehicle.plate).all()
    active_vehicles = [v for v in vehicles if v.status != 'MAINTENANCE']
    maintenance_vehicles = [v for v in vehicles if v.status == 'MAINTENANCE']
    avg_vehicle = (total / Decimal(len(vehicles))).quantize(Decimal('0.01')) if vehicles else Decimal('0')

    today = local_today()
    cq = DailyChecklist.query.filter_by(checklist_date=today, is_deleted=False)
    if base_code != 'ALL':
        cq = cq.filter(DailyChecklist.base_code == base_code)
    if not current_user.is_admin:
        cq = cq.filter(DailyChecklist.driver_id == current_user.id)
    checklist_today = cq.count()

    grouped = {}
    for e in current_rows:
        item = grouped.setdefault(e.vehicle_id, {'vehicle': e.vehicle, 'total': Decimal('0'), 'fuel': Decimal('0'), 'maintenance': Decimal('0'), 'count': 0})
        item['total'] += Decimal(e.amount)
        item['count'] += 1
        if e.expense_type == 'FUEL':
            item['fuel'] += Decimal(e.amount)
        elif e.expense_type == 'MAINTENANCE':
            item['maintenance'] += Decimal(e.amount)
    vehicle_costs = sorted(grouped.values(), key=lambda x: x['total'], reverse=True)

    last_months = []
    cursor = start
    for _ in range(6):
        if cursor.month == 1:
            ms = date(cursor.year - 1, 12, 1)
        else:
            ms = date(cursor.year, cursor.month - 1, 1)
        month_total = _money_sum(_expense_query(ms, cursor, base_code).all())
        last_months.append({'month': ms.strftime('%Y-%m'), 'label': _month_label(ms), 'total': month_total})
        cursor = ms

    return render_template(
        'dashboard20.html',
        month=start.strftime('%Y-%m'), month_label=_month_label(start), base_code=base_code,
        bases=BASES, is_global=is_global_admin(),
        total=total, previous_total=previous_total, delta=delta,
        fuel=fuel, maintenance=maintenance, motorcycle=motorcycle, car=car,
        vehicles=vehicles, active_count=len(active_vehicles), maintenance_count=len(maintenance_vehicles),
        avg_vehicle=avg_vehicle, checklist_today=checklist_today,
        vehicle_costs=vehicle_costs[:10], recent_expenses=current_rows[:10], last_months=last_months,
    )


@enterprise20_bp.route('/costs')
@login_required
def costs():
    start, end, _ = _month_bounds(request.args.get('month'))
    base_code = _selected_base()
    category = (request.args.get('category') or 'ALL').upper()
    q = _expense_query(start, end, base_code)
    if category == 'FUEL':
        q = q.filter(Expense.expense_type == 'FUEL')
    elif category == 'MAINTENANCE':
        q = q.filter(Expense.expense_type == 'MAINTENANCE')
    rows = q.order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    total = _money_sum(rows)
    grouped = {}
    for e in rows:
        item = grouped.setdefault(e.vehicle_id, {'vehicle': e.vehicle, 'total': Decimal('0'), 'fuel': Decimal('0'), 'maintenance': Decimal('0'), 'count': 0})
        item['total'] += Decimal(e.amount)
        item['count'] += 1
        if e.expense_type == 'FUEL': item['fuel'] += Decimal(e.amount)
        if e.expense_type == 'MAINTENANCE': item['maintenance'] += Decimal(e.amount)
    by_vehicle = sorted(grouped.values(), key=lambda x: x['total'], reverse=True)
    return render_template('executive/costs.html', month=start.strftime('%Y-%m'), month_label=_month_label(start), base_code=base_code, bases=BASES, is_global=is_global_admin(), category=category, total=total, rows=rows, by_vehicle=by_vehicle)


@enterprise20_bp.route('/vehicle/<int:vehicle_id>')
@login_required
def vehicle_costs(vehicle_id):
    start, end, _ = _month_bounds(request.args.get('month'))
    base_code = _selected_base()
    vehicle = db.session.get(Vehicle, vehicle_id) or abort(404)
    if base_code != 'ALL' and vehicle.base_code != base_code:
        abort(403)
    if not current_user.is_admin and (not current_user.vehicle or current_user.vehicle.id != vehicle.id):
        abort(403)

    expenses = _expense_query(start, end, base_code).filter(Expense.vehicle_id == vehicle.id).order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    total = _money_sum(expenses)
    fuel = _money_sum(expenses, lambda e: e.expense_type == 'FUEL')
    maintenance = _money_sum(expenses, lambda e: e.expense_type == 'MAINTENANCE')
    uses = DailyChecklist.query.filter(
        DailyChecklist.vehicle_id == vehicle.id,
        DailyChecklist.checklist_date >= start,
        DailyChecklist.checklist_date < end,
        DailyChecklist.is_deleted.is_(False),
    ).order_by(DailyChecklist.created_at.desc()).all()
    return render_template('executive/vehicle_costs.html', vehicle=vehicle, month=start.strftime('%Y-%m'), month_label=_month_label(start), base_code=base_code, total=total, fuel=fuel, maintenance=maintenance, expenses=expenses, uses=uses)


def init_enterprise20(app):
    app.register_blueprint(enterprise20_bp)
    app.view_functions['main.dashboard'] = dashboard_v2
