from decimal import Decimal

from flask import render_template, request
from flask_login import current_user, login_required
from sqlalchemy import and_, case, func
from sqlalchemy.orm import selectinload

from .models import (
    db, User, Vehicle, Expense, MaintenanceDetail, DailyChecklist,
    AdminNotification, OilChange, OilAlertStatus,
)
from .time_utils import local_today


def _scope(query, model):
    """Aplica a base explicitamente nas consultas agregadas.

    O Enterprise 1.8 já possui filtro global por base para entidades ORM, mas
    consultas somente com colunas/agregações podem não passar pelo mesmo
    caminho em todos os bancos. Mantemos o isolamento também aqui.
    """
    if not current_user.is_authenticated or current_user.is_global_admin:
        return query
    return query.filter(model.base_code == current_user.base_code)


def fast_build_oil_statuses(vehicle_id=None):
    """Mesmo resultado do cálculo anterior usando consultas em lote.

    Antes eram executadas duas ou mais consultas para cada moto. Agora:
    veículos, trocas de óleo e checklists são carregados em lotes e tratados
    em memória. Isso reduz bastante a latência com várias bases/motos.
    """
    vq = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE')
    if vehicle_id:
        vq = vq.filter_by(id=vehicle_id)
    vehicles = vq.order_by(Vehicle.plate).all()
    if not vehicles:
        return []

    vehicle_ids = [v.id for v in vehicles]

    oq = OilChange.query.outerjoin(Expense, OilChange.expense_id == Expense.id).filter(
        OilChange.vehicle_id.in_(vehicle_ids),
        (OilChange.expense_id.is_(None)) | (Expense.is_deleted.is_(False)),
    ).order_by(OilChange.vehicle_id, OilChange.change_date.desc(), OilChange.id.desc())
    oil_rows = oq.all()

    last_by_vehicle = {}
    for row in oil_rows:
        last_by_vehicle.setdefault(row.vehicle_id, row)

    dated = [row for row in last_by_vehicle.values() if row.change_date]
    checklist_max = {}
    if dated:
        min_date = min(row.change_date for row in dated)
        cq = db.session.query(
            DailyChecklist.vehicle_id,
            DailyChecklist.checklist_date,
            DailyChecklist.odometer,
        ).filter(
            DailyChecklist.vehicle_id.in_(vehicle_ids),
            DailyChecklist.is_deleted.is_(False),
            DailyChecklist.checklist_date >= min_date,
        )
        for vid, cdate, km in cq.all():
            last = last_by_vehicle.get(vid)
            if not last or cdate < last.change_date:
                continue
            if km is not None:
                checklist_max[vid] = max(checklist_max.get(vid, km), km)

    result = []
    for vehicle in vehicles:
        last = last_by_vehicle.get(vehicle.id)
        if not last:
            result.append({
                'vehicle': vehicle, 'oil_change': None, 'base_km': None,
                'current_km': vehicle.current_km or 0, 'traveled_km': 0,
                'remaining_km': 990, 'target_km': None, 'level': 'neutral',
                'status_label': 'Sem troca registrada',
            })
            continue

        current_km = checklist_max.get(vehicle.id, last.odometer)
        current_km = max(current_km or 0, last.odometer)
        traveled = max(0, current_km - last.odometer)
        remaining = 990 - traveled
        target = last.odometer + 990
        if remaining <= 0:
            level, label = 'danger', 'Vencida'
        elif remaining <= 50:
            level, label = 'danger', 'Urgente'
        elif remaining <= 200:
            level, label = 'warning', 'Atenção'
        else:
            level, label = 'success', 'Normal'
        result.append({
            'vehicle': vehicle, 'oil_change': last,
            'base_km': last.odometer, 'current_km': current_km,
            'traveled_km': traveled, 'remaining_km': remaining,
            'target_km': target, 'level': level, 'status_label': label,
        })
    return result


def fast_build_oil_alerts(vehicle_id=None):
    statuses = fast_build_oil_statuses(vehicle_id)
    alertable = [s for s in statuses if s['oil_change'] and s['remaining_km'] <= 200]
    if not alertable:
        return []

    vehicle_ids = [s['vehicle'].id for s in alertable]
    change_ids = [s['oil_change'].id for s in alertable]
    sq = OilAlertStatus.query.filter(
        OilAlertStatus.vehicle_id.in_(vehicle_ids),
        OilAlertStatus.oil_change_id.in_(change_ids),
    )
    sent_map = {(s.vehicle_id, s.oil_change_id, s.level): s for s in sq.all()}

    result = []
    for info in alertable:
        remaining = info['remaining_km']
        if remaining <= 0:
            title = 'Troca de óleo vencida'
        elif remaining <= 50:
            title = 'Troca de óleo urgente'
        else:
            title = 'Troca de óleo próxima'
        saved = sent_map.get((info['vehicle'].id, info['oil_change'].id, info['level']))
        result.append({
            **info,
            'title': title,
            'detail': (
                f"Base {info['base_km']} km · Atual {info['current_km']} km · "
                f"Rodados {info['traveled_km']} km · "
                + (f"Restam {remaining} km" if remaining >= 0 else f"Vencida há {abs(remaining)} km")
            ),
            'message_sent': bool(saved and saved.message_sent_at),
            'sent_at': saved.message_sent_at if saved else None,
        })
    return result


def _expense_filter(month_start):
    filters = [Expense.expense_date >= month_start, Expense.is_deleted.is_(False)]
    if not current_user.is_admin:
        filters.append(Expense.created_by_id == current_user.id)
    if not current_user.is_global_admin:
        filters.append(Expense.base_code == current_user.base_code)
    return filters


@login_required
def fast_dashboard():
    """Dashboard com agregações no banco e apenas registros visíveis na tela."""
    from .routes import car_plate_photo_ids

    today = local_today()
    month_start = today.replace(day=1)
    filters = _expense_filter(month_start)

    totals = db.session.query(
        func.coalesce(func.sum(Expense.amount), 0),
        func.coalesce(func.sum(case(
            (and_(Expense.expense_type == 'FUEL', Expense.asset_type == 'MOTORCYCLE'), Expense.amount),
            else_=0,
        )), 0),
        func.coalesce(func.sum(case(
            (and_(Expense.expense_type == 'FUEL', Expense.asset_type == 'CAR'), Expense.amount),
            else_=0,
        )), 0),
        func.coalesce(func.sum(case(
            (Expense.expense_type == 'MAINTENANCE', Expense.amount), else_=0,
        )), 0),
    ).filter(*filters).one()

    total = Decimal(totals[0] or 0)
    motorcycle_fuel = Decimal(totals[1] or 0)
    car_fuel = Decimal(totals[2] or 0)
    maintenance_total = Decimal(totals[3] or 0)

    oil = Decimal('0')
    oil_rows = db.session.query(Expense.amount, MaintenanceDetail.oil_amount).join(
        MaintenanceDetail, MaintenanceDetail.expense_id == Expense.id
    ).filter(
        *filters,
        Expense.expense_type == 'MAINTENANCE',
        MaintenanceDetail.is_oil_change.is_(True),
        MaintenanceDetail.oil_amount.isnot(None),
    ).all()
    for amount, oil_amount in oil_rows:
        explicit = max(Decimal('0'), Decimal(oil_amount or 0))
        oil += min(explicit, Decimal(amount or 0))
    maintenance_other = maintenance_total - oil

    recent_q = Expense.query.options(
        selectinload(Expense.vehicle),
        selectinload(Expense.created_by),
        selectinload(Expense.responsible_driver),
    ).filter(*filters).order_by(Expense.expense_date.desc(), Expense.id.desc())
    expenses = recent_q.limit(8).all()

    active_vehicle = None
    try:
        from .enterprise19 import active_vehicle as _active_vehicle
        active_vehicle = _active_vehicle()
    except Exception:
        active_vehicle = None

    vehicle_scope = active_vehicle.id if (not current_user.is_admin and active_vehicle) else None
    oil_statuses = fast_build_oil_statuses(vehicle_scope) if current_user.is_admin or vehicle_scope else []
    alerts = fast_build_oil_alerts(vehicle_scope) if current_user.is_admin or vehicle_scope else []

    mq = Vehicle.query.options(selectinload(Vehicle.driver)).filter_by(
        vehicle_type='MOTORCYCLE', status='MAINTENANCE'
    ).order_by(Vehicle.plate)
    maintenance_motos = mq.all()
    maintenance_vehicles = []
    if maintenance_motos:
        ids = [v.id for v in maintenance_motos]
        eq = Expense.query.options(selectinload(Expense.maintenance)).join(MaintenanceDetail).filter(
            Expense.vehicle_id.in_(ids),
            Expense.is_deleted.is_(False),
            MaintenanceDetail.status == 'IN_PROGRESS',
        ).order_by(Expense.expense_date.desc(), Expense.id.desc())
        latest = {}
        for row in eq.all():
            latest.setdefault(row.vehicle_id, row)
        maintenance_vehicles = [{'vehicle': v, 'expense': latest.get(v.id)} for v in maintenance_motos]

    cq = DailyChecklist.query.filter_by(checklist_date=today, is_deleted=False)
    if not current_user.is_admin:
        cq = cq.filter_by(driver_id=current_user.id)
    today_checklist_count = cq.count()

    pending_notifications = 0
    if current_user.is_admin:
        pending_notifications = AdminNotification.query.filter_by(is_read=False).count()

    recent_cq = DailyChecklist.query.options(
        selectinload(DailyChecklist.vehicle),
        selectinload(DailyChecklist.driver),
    ).filter_by(is_deleted=False)
    if not current_user.is_admin:
        recent_cq = recent_cq.filter_by(driver_id=current_user.id)
    recent_checklists = recent_cq.order_by(
        DailyChecklist.created_at.desc(), DailyChecklist.id.desc()
    ).limit(5).all()

    driver_costs = []
    if current_user.is_admin:
        dq = db.session.query(User.name, func.sum(Expense.amount)).join(
            Expense, Expense.created_by_id == User.id
        ).filter(*filters).group_by(User.id, User.name).order_by(func.sum(Expense.amount).desc()).limit(10)
        driver_costs = [(name, Decimal(value or 0)) for name, value in dq.all()]

    return render_template(
        'dashboard.html', expenses=expenses, total=total,
        motorcycle_total=Decimal('0'), car_total=Decimal('0'),
        motorcycle_fuel=motorcycle_fuel, car_fuel=car_fuel,
        maint=maintenance_other, oil=oil, alerts=alerts, oil_statuses=oil_statuses,
        motorcycles=[], cars=[], maintenance_vehicles=maintenance_vehicles,
        car_plate_photo_ids=car_plate_photo_ids(expenses),
        today=today, today_checklist_count=today_checklist_count,
        pending_notifications=pending_notifications,
        recent_checklists=recent_checklists, driver_costs=driver_costs,
    )


def fast_enterprise18_context():
    """Contexto global sem consultas N+1 no painel do gerente."""
    from .enterprise18 import BASES, current_base, is_base_admin, is_global_admin, _driver_action_status

    if not current_user.is_authenticated:
        return {'e18': None}
    data = {
        'base': current_base(), 'is_global': is_global_admin(),
        'is_base_admin': is_base_admin(), 'bases': BASES,
    }
    if current_user.role == 'DRIVER':
        data['driver_action'] = _driver_action_status(current_user)
        vehicle = None
        try:
            from .enterprise19 import active_vehicle
            vehicle = active_vehicle()
        except Exception:
            vehicle = current_user.vehicle
        status = fast_build_oil_statuses(vehicle.id) if vehicle else []
        data['oil'] = status[0] if status else None
    elif current_user.is_admin:
        statuses = fast_build_oil_statuses()
        today = local_today()
        drivers_q = User.query.filter_by(role='DRIVER', active=True)
        drivers = drivers_q.with_entities(User.id).all()
        driver_ids = [row[0] for row in drivers]
        completed = set()
        if driver_ids:
            rows = db.session.query(DailyChecklist.driver_id).filter(
                DailyChecklist.driver_id.in_(driver_ids),
                DailyChecklist.checklist_date == today,
                DailyChecklist.checklist_type == 'RETIRADA',
                DailyChecklist.is_deleted.is_(False),
            ).distinct().all()
            completed = {row[0] for row in rows}
        data['fleet'] = {
            'total': len(statuses),
            'danger': sum(1 for s in statuses if s['level'] == 'danger'),
            'warning': sum(1 for s in statuses if s['level'] == 'warning'),
            'none': sum(1 for s in statuses if s['level'] in ('none', 'neutral')),
            'success': sum(1 for s in statuses if s['level'] == 'success'),
            'retirada_pendente': max(0, len(driver_ids) - len(completed)),
        }
    return {'e18': data}


def _install_indexes_once():
    """Índices compostos para as consultas mais frequentes."""
    from sqlalchemy import text
    statements = [
        'CREATE INDEX IF NOT EXISTS ix_expense_base_date_deleted ON expense (base_code, expense_date, is_deleted)',
        'CREATE INDEX IF NOT EXISTS ix_expense_vehicle_type_date ON expense (vehicle_id, expense_type, expense_date)',
        'CREATE INDEX IF NOT EXISTS ix_checklist_base_date_deleted ON daily_checklist (base_code, checklist_date, is_deleted)',
        'CREATE INDEX IF NOT EXISTS ix_checklist_vehicle_date_deleted ON daily_checklist (vehicle_id, checklist_date, is_deleted)',
        'CREATE INDEX IF NOT EXISTS ix_checklist_driver_date_type ON daily_checklist (driver_id, checklist_date, checklist_type)',
        'CREATE INDEX IF NOT EXISTS ix_oil_change_vehicle_date ON oil_change (vehicle_id, change_date)',
        'CREATE INDEX IF NOT EXISTS ix_notification_base_read ON admin_notification (base_code, is_read)',
    ]
    for sql in statements:
        db.session.execute(text(sql))
    db.session.commit()


def init_performance(app):
    from . import routes

    routes.build_oil_statuses = fast_build_oil_statuses
    routes.build_oil_alerts = fast_build_oil_alerts
    app.view_functions['main.dashboard'] = fast_dashboard

    # Substitui somente o context processor pesado do Enterprise 1.8.
    processors = app.template_context_processors.get(None, [])
    for idx, fn in enumerate(list(processors)):
        if getattr(fn, '__name__', '') == 'enterprise18_context':
            processors[idx] = fast_enterprise18_context

    # As tabelas já existem em produção; em bancos novos de CI esse bloco pode
    # rodar antes do create_all, então falhar aqui não deve impedir o boot.
    try:
        with app.app_context():
            _install_indexes_once()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
