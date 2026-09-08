from .models import db, Vehicle, Expense, DailyChecklist, OilChange, OilAlertStatus

OIL_INTERVAL_KM = 990


def _latest_valid_checklist(vehicle_id, since_date=None):
    q = DailyChecklist.query.filter(
        DailyChecklist.vehicle_id == vehicle_id,
        DailyChecklist.is_deleted.is_(False),
    )
    if since_date is not None:
        q = q.filter(DailyChecklist.checklist_date >= since_date)
    # IMPORTANTE: usa o checklist cronologicamente mais recente, e nao MAX(odometer).
    # Um unico KM digitado errado no passado nao pode contaminar a moto para sempre.
    return q.order_by(
        DailyChecklist.checklist_date.desc(),
        DailyChecklist.created_at.desc(),
        DailyChecklist.id.desc(),
    ).first()


def build_oil_statuses_safe(vehicle_id=None):
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
            result.append({
                'vehicle': vehicle, 'oil_change': None, 'base_km': None,
                'current_km': int(vehicle.current_km or 0), 'traveled_km': 0,
                'remaining_km': OIL_INTERVAL_KM, 'target_km': None,
                'level': 'neutral', 'status_label': 'Sem troca registrada',
            })
            continue

        latest = _latest_valid_checklist(vehicle.id, last_change.change_date)
        base_km = int(last_change.odometer or 0)
        current_km = int(latest.odometer) if latest and latest.odometer is not None else base_km

        # Se o checklist mais recente for anterior ao KM da troca, a troca e a referencia.
        # Assim nunca exibimos distancia negativa ou centenas de milhares de km por um registro antigo ruim.
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
            'vehicle': vehicle, 'oil_change': last_change,
            'base_km': base_km, 'current_km': current_km,
            'traveled_km': traveled, 'remaining_km': remaining,
            'target_km': target, 'level': level, 'status_label': label,
        })
    return result


def build_oil_alerts_safe(vehicle_id=None):
    result = []
    for status_info in build_oil_statuses_safe(vehicle_id):
        last = status_info['oil_change']
        remaining = status_info['remaining_km']
        if not last or remaining > 200:
            continue
        if remaining <= 0:
            title = 'Troca de óleo vencida'
        elif remaining <= 50:
            title = 'Troca de óleo urgente'
        else:
            title = 'Troca de óleo próxima'
        status = OilAlertStatus.query.filter_by(
            vehicle_id=status_info['vehicle'].id,
            oil_change_id=last.id,
            level=status_info['level'],
        ).first()
        result.append({
            **status_info,
            'title': title,
            'detail': (
                f"Base {status_info['base_km']} km · Atual {status_info['current_km']} km · "
                f"Rodados {status_info['traveled_km']} km · "
                + (f"Restam {remaining} km" if remaining >= 0 else f"Vencida há {abs(remaining)} km")
            ),
            'message_sent': bool(status and status.message_sent_at),
            'sent_at': status.message_sent_at if status else None,
        })
    return result


def init_fleet_intelligence_upgrade(app):
    # Substitui as funcoes usadas pelo dashboard/alertas sem precisar reescrever routes.py.
    from . import routes
    routes.build_oil_statuses = build_oil_statuses_safe
    routes.build_oil_alerts = build_oil_alerts_safe
