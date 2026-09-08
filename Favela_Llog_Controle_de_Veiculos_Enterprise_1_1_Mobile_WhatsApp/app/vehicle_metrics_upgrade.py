from flask import request
from flask_login import current_user

from .models import Vehicle, Expense, DailyChecklist


def _visible_vehicles():
    q = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE')
    if not current_user.is_global_admin:
        q = q.filter_by(base_code=current_user.base_code)
    if not current_user.is_admin:
        q = q.filter_by(driver_id=current_user.id)
    return q.order_by(Vehicle.plate).all()


def _build_metrics(vehicles):
    if not vehicles:
        return {}
    ids = [v.id for v in vehicles]
    metrics = {v.id: {
        'current_km': int(v.current_km or 0),
        'last_checklist_km': None,
        'previous_checklist_km': None,
        'checklist_delta_km': None,
        'last_fuel_km': None,
        'previous_fuel_km': None,
        'fuel_cycle_km': None,
        'since_fuel_km': None,
    } for v in vehicles}

    crows = DailyChecklist.query.filter(
        DailyChecklist.vehicle_id.in_(ids),
        DailyChecklist.is_deleted.is_(False),
    ).with_entities(
        DailyChecklist.vehicle_id,
        DailyChecklist.odometer,
        DailyChecklist.checklist_date,
        DailyChecklist.created_at,
        DailyChecklist.id,
    ).order_by(
        DailyChecklist.vehicle_id,
        DailyChecklist.checklist_date.desc(),
        DailyChecklist.created_at.desc(),
        DailyChecklist.id.desc(),
    ).all()
    seen = {}
    for vid, km, cdate, created_at, cid in crows:
        if km is None:
            continue
        n = seen.get(vid, 0)
        if n == 0:
            metrics[vid]['last_checklist_km'] = int(km)
        elif n == 1:
            metrics[vid]['previous_checklist_km'] = int(km)
        else:
            continue
        seen[vid] = n + 1
    for vid, m in metrics.items():
        if m['last_checklist_km'] is not None and m['previous_checklist_km'] is not None:
            m['checklist_delta_km'] = max(0, m['last_checklist_km'] - m['previous_checklist_km'])

    frows = Expense.query.filter(
        Expense.vehicle_id.in_(ids),
        Expense.expense_type == 'FUEL',
        Expense.asset_type == 'MOTORCYCLE',
        Expense.is_deleted.is_(False),
    ).with_entities(
        Expense.vehicle_id,
        Expense.odometer,
        Expense.expense_date,
        Expense.id,
    ).order_by(
        Expense.vehicle_id,
        Expense.expense_date.desc(),
        Expense.id.desc(),
    ).all()
    seen = {}
    for vid, km, edate, eid in frows:
        if km is None:
            continue
        n = seen.get(vid, 0)
        if n == 0:
            metrics[vid]['last_fuel_km'] = int(km)
        elif n == 1:
            metrics[vid]['previous_fuel_km'] = int(km)
        else:
            continue
        seen[vid] = n + 1
    for vid, m in metrics.items():
        if m['last_fuel_km'] is not None:
            m['since_fuel_km'] = max(0, m['current_km'] - m['last_fuel_km'])
        if m['last_fuel_km'] is not None and m['previous_fuel_km'] is not None:
            m['fuel_cycle_km'] = max(0, m['last_fuel_km'] - m['previous_fuel_km'])
    return metrics


def init_vehicle_metrics_upgrade(app):
    @app.context_processor
    def vehicle_metrics_context():
        if not current_user.is_authenticated:
            return {'vehicle_metrics': {}}
        if request.endpoint not in {'main.dashboard', 'main.fuel_new'}:
            return {'vehicle_metrics': {}}
        try:
            vehicles = _visible_vehicles()
            return {'vehicle_metrics': _build_metrics(vehicles)}
        except Exception:
            app.logger.exception('Falha ao calcular métricas de KM da frota')
            return {'vehicle_metrics': {}}
