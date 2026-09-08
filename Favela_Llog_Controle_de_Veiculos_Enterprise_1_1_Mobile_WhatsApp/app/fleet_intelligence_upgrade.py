from .models import db, Vehicle, Expense, DailyChecklist, OilChange, OilAlertStatus

OIL_INTERVAL_KM = 990


def _latest_checklist_by_type(vehicle_id, checklist_type, since_date=None):
    q = DailyChecklist.query.filter(
        DailyChecklist.vehicle_id == vehicle_id,
        DailyChecklist.checklist_type == checklist_type,
        DailyChecklist.is_deleted.is_(False),
    )
    if since_date is not None:
        q = q.filter(DailyChecklist.checklist_date >= since_date)
    return q.order_by(
        DailyChecklist.checklist_date.desc(),
        DailyChecklist.created_at.desc(),
        DailyChecklist.id.desc(),
    ).first()


def _latest_operational_km(vehicle_id, since_date=None):
    """Usa somente os checklists operacionais de retirada/devolucao.

    O KM cadastral da moto, abastecimentos e checklists LEGACY nao entram no
    calculo da troca de oleo. Entre a ultima RETIRADA e a ultima DEVOLUCAO,
    vale o registro cronologicamente mais recente. Em caso de mesma data,
    created_at/id definem qual foi realmente o ultimo lancamento.
    """
    retirada = _latest_checklist_by_type(vehicle_id, 'RETIRADA', since_date)
    devolucao = _latest_checklist_by_type(vehicle_id, 'DEVOLUCAO', since_date)
    candidates = [c for c in (retirada, devolucao) if c and c.odometer is not None]
    if not candidates:
        return None, retirada, devolucao
    latest = max(
        candidates,
        key=lambda c: (c.checklist_date, c.created_at, c.id),
    )
    return int(latest.odometer), retirada, devolucao


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
            current_km, retirada, devolucao = _latest_operational_km(vehicle.id)
            result.append({
                'vehicle': vehicle,
                'oil_change': None,
                'base_km': None,
                'current_km': current_km if current_km is not None else 0,
                'traveled_km': 0,
                'remaining_km': OIL_INTERVAL_KM,
                'target_km': None,
                'level': 'neutral',
                'status_label': 'Sem troca registrada',
                'last_withdrawal_km': int(retirada.odometer) if retirada and retirada.odometer is not None else None,
                'last_return_km': int(devolucao.odometer) if devolucao and devolucao.odometer is not None else None,
            })
            continue

        base_km = int(last_change.odometer or 0)
        current_km, retirada, devolucao = _latest_operational_km(vehicle.id, last_change.change_date)

        # Se ainda nao houve retirada/devolucao depois da troca, a propria troca
        # e a referencia atual e faltam os 990 km completos.
        if current_km is None:
            current_km = base_km

        # Um checklist nao pode fazer o ciclo voltar para tras. Se um registro
        # operacional vier menor que o KM da troca, mantemos a base da troca.
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
            'last_withdrawal_km': int(retirada.odometer) if retirada and retirada.odometer is not None else None,
            'last_return_km': int(devolucao.odometer) if devolucao and devolucao.odometer is not None else None,
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
        retirada = status_info.get('last_withdrawal_km')
        devolucao = status_info.get('last_return_km')
        result.append({
            **status_info,
            'title': title,
            'detail': (
                f"Troca em {status_info['base_km']} km · "
                f"Última retirada {retirada if retirada is not None else '-'} km · "
                f"Última devolução {devolucao if devolucao is not None else '-'} km · "
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
