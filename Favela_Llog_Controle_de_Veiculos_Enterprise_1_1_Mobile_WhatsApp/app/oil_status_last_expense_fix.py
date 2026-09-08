from .models import db, Vehicle, Expense, OilChange, OilAlertStatus


def _latest_vehicle_odometer(vehicle_id, min_date=None):
    q = Expense.query.filter(
        Expense.vehicle_id == vehicle_id,
        Expense.asset_type == 'MOTORCYCLE',
        Expense.is_deleted.is_(False),
        Expense.odometer.isnot(None),
    )
    if min_date is not None:
        q = q.filter(Expense.expense_date >= min_date)
    row = q.order_by(Expense.expense_date.desc(), Expense.id.desc()).first()
    return int(row.odometer) if row and row.odometer is not None else None


def _build_oil_statuses(vehicle_id=None):
    q = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE')
    if vehicle_id:
        q = q.filter_by(id=vehicle_id)

    result = []
    for vehicle in q.order_by(Vehicle.plate).all():
        last_change = OilChange.query.outerjoin(Expense, OilChange.expense_id == Expense.id).filter(
            OilChange.vehicle_id == vehicle.id,
            (OilChange.expense_id.is_(None)) | (Expense.is_deleted.is_(False)),
        ).order_by(OilChange.change_date.desc(), OilChange.id.desc()).first()

        if not last_change:
            current_km = _latest_vehicle_odometer(vehicle.id)
            if current_km is None:
                current_km = int(vehicle.current_km or 0)
            result.append({
                'vehicle': vehicle,
                'oil_change': None,
                'base_km': None,
                'current_km': current_km,
                'traveled_km': 0,
                'remaining_km': 990,
                'target_km': None,
                'level': 'neutral',
                'status_label': 'Sem troca registrada',
            })
            continue

        base_km = int(last_change.odometer or 0)
        current_km = _latest_vehicle_odometer(vehicle.id, last_change.change_date)
        if current_km is None:
            current_km = base_km

        # O último lançamento da moto é a fonte operacional para o KM atual.
        # Nunca deixa um lançamento anterior à troca produzir distância negativa.
        current_km = max(base_km, int(current_km))
        traveled = max(0, current_km - base_km)
        remaining = 990 - traveled
        target = base_km + 990

        if remaining <= 0:
            level, label = 'danger', 'Vencida'
        elif remaining <= 50:
            level, label = 'danger', 'Urgente'
        elif remaining <= 200:
            level, label = 'warning', 'Atenção'
        else:
            level, label = 'success', 'Normal'

        result.append({
            'vehicle': vehicle,
            'oil_change': last_change,
            'base_km': base_km,
            'current_km': current_km,
            'traveled_km': traveled,
            'remaining_km': remaining,
            'target_km': target,
            'level': level,
            'status_label': label,
        })
    return result


def init_oil_status_last_expense_fix(app):
    # routes.build_oil_alerts resolve build_oil_statuses pelo namespace do módulo
    # a cada chamada; substituir aqui corrige dashboard, alertas e notificações.
    from . import routes
    routes.build_oil_statuses = _build_oil_statuses
