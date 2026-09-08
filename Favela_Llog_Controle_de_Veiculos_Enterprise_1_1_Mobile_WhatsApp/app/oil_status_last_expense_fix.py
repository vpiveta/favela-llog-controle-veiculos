from .models import Vehicle, Expense, OilChange, DailyChecklist

OIL_INTERVAL_KM = 990


def _latest_checklist_by_type(vehicle_id, checklist_type, min_date=None):
    q = DailyChecklist.query.filter(
        DailyChecklist.vehicle_id == vehicle_id,
        DailyChecklist.checklist_type == checklist_type,
        DailyChecklist.is_deleted.is_(False),
        DailyChecklist.odometer.isnot(None),
    )
    if min_date is not None:
        q = q.filter(DailyChecklist.checklist_date >= min_date)
    return q.order_by(
        DailyChecklist.checklist_date.desc(),
        DailyChecklist.created_at.desc(),
        DailyChecklist.id.desc(),
    ).first()


def _latest_operational_checklist(vehicle_id, min_date=None):
    retirada = _latest_checklist_by_type(vehicle_id, 'RETIRADA', min_date)
    devolucao = _latest_checklist_by_type(vehicle_id, 'DEVOLUCAO', min_date)
    candidates = [c for c in (retirada, devolucao) if c is not None]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda c: (c.checklist_date, c.created_at, c.id),
    )


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
            latest = _latest_operational_checklist(vehicle.id)
            current_km = int(latest.odometer) if latest and latest.odometer is not None else int(vehicle.current_km or 0)
            result.append({
                'vehicle': vehicle,
                'oil_change': None,
                'base_km': None,
                'current_km': current_km,
                'traveled_km': 0,
                'remaining_km': OIL_INTERVAL_KM,
                'target_km': None,
                'level': 'neutral',
                'status_label': 'Sem troca registrada',
            })
            continue

        base_km = int(last_change.odometer or 0)
        latest = _latest_operational_checklist(vehicle.id, last_change.change_date)
        current_km = int(latest.odometer) if latest and latest.odometer is not None else base_km

        # O cálculo usa SOMENTE a última RETIRADA/DEVOLUÇÃO válida após a troca.
        # Evita que abastecimentos, edições manuais ou lançamentos antigos contaminem o ciclo.
        if current_km < base_km:
            current_km = base_km

        traveled = max(0, current_km - base_km)
        remaining = OIL_INTERVAL_KM - traveled
        target = base_km + OIL_INTERVAL_KM

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
    from . import routes
    routes.build_oil_statuses = _build_oil_statuses
