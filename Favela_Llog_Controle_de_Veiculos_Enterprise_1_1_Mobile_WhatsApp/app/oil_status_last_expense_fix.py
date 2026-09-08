from .models import Vehicle, Expense, OilChange, DailyChecklist

OIL_INTERVAL_KM = 990
MAX_PLAUSIBLE_DAILY_DELTA = 1500
MAX_ANCHOR_DELTA = 5000


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


def _pick_operational_km(vehicle, min_date=None):
    retirada = _latest_checklist_by_type(vehicle.id, 'RETIRADA', min_date)
    devolucao = _latest_checklist_by_type(vehicle.id, 'DEVOLUCAO', min_date)
    candidates = [c for c in (retirada, devolucao) if c is not None]
    if not candidates:
        return None, None

    # Se retirada e devolução forem coerentes, usa o registro cronologicamente mais recente.
    if len(candidates) == 2:
        r_km = int(retirada.odometer or 0)
        d_km = int(devolucao.odometer or 0)
        if abs(r_km - d_km) <= MAX_PLAUSIBLE_DAILY_DELTA:
            chosen = max(candidates, key=lambda c: (c.checklist_date, c.created_at, c.id))
            return int(chosen.odometer or 0), chosen

    # Quando há salto absurdo entre retirada/devolução, usa o KM atual corrigido da moto
    # apenas como âncora para descobrir qual checklist é plausível.
    anchor = int(vehicle.current_km or 0)
    plausible = []
    if anchor > 0:
        for c in candidates:
            km = int(c.odometer or 0)
            if abs(km - anchor) <= MAX_ANCHOR_DELTA:
                plausible.append(c)

    if plausible:
        chosen = min(plausible, key=lambda c: abs(int(c.odometer or 0) - anchor))
        return int(chosen.odometer or 0), chosen

    # Última barreira: rejeita leitura claramente contaminada (ex.: 468.000 km)
    # quando a moto cadastrada está em uma faixa muito menor.
    if anchor > 0:
        chosen = min(candidates, key=lambda c: abs(int(c.odometer or 0) - anchor))
        km = int(chosen.odometer or 0)
        if abs(km - anchor) > MAX_ANCHOR_DELTA:
            return anchor, None
        return km, chosen

    chosen = min(candidates, key=lambda c: int(c.odometer or 0))
    return int(chosen.odometer or 0), chosen


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

        current_km, source = _pick_operational_km(vehicle, last_change.change_date if last_change else None)

        if not last_change:
            current_km = current_km if current_km is not None else int(vehicle.current_km or 0)
            result.append({
                'vehicle': vehicle, 'oil_change': None, 'base_km': None,
                'current_km': current_km, 'traveled_km': 0,
                'remaining_km': OIL_INTERVAL_KM, 'target_km': None,
                'level': 'neutral', 'status_label': 'Sem troca registrada',
                'km_source': source.checklist_type if source else 'CADASTRO',
            })
            continue

        base_km = int(last_change.odometer or 0)
        if current_km is None:
            current_km = int(vehicle.current_km or base_km)

        # Se o KM da troca também estiver acima da realidade atual por erro histórico,
        # não produz número negativo absurdo: mantém o ciclo neutro para conferência.
        if base_km > current_km + MAX_ANCHOR_DELTA:
            base_km = current_km

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
            'km_source': source.checklist_type if source else 'CADASTRO',
        })
    return result


def init_oil_status_last_expense_fix(app):
    from . import routes
    routes.build_oil_statuses = _build_oil_statuses
