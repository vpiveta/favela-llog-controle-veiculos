import csv
import io
import os
from datetime import datetime
from urllib.parse import quote
from urllib.request import Request, urlopen

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, url_for,
    Response, session as flask_session, g, has_request_context
)
from flask_login import current_user, login_required
from sqlalchemy import event, func, case
from sqlalchemy.orm import with_loader_criteria, Session

from .models import (
    db, User, Vehicle, Expense, DailyChecklist, AdminNotification,
    OilChange, OilAlertStatus, StoredFile, AuditLog
)
from .time_utils import local_today, utc_now

enterprise18_bp = Blueprint('enterprise18', __name__)
BASES = ('SDA9', 'SLI9', 'SDI9')
SCOPED_MODELS = (User, Vehicle, Expense, DailyChecklist, AdminNotification, OilChange, OilAlertStatus, StoredFile, AuditLog)
_EVENTS_INSTALLED = False


def normalize_base(value):
    value = (value or '').upper().strip()
    return value if value in BASES else 'SDA9'


def is_global_admin(user=None):
    user = user or current_user
    return bool(getattr(user, 'is_authenticated', False) and getattr(user, 'role', '') in ('ADMIN_GLOBAL', 'ADMIN'))


def is_base_admin(user=None):
    user = user or current_user
    return bool(getattr(user, 'is_authenticated', False) and getattr(user, 'role', '') == 'ADMIN_BASE')


def current_base():
    if not getattr(current_user, 'is_authenticated', False):
        return None
    return normalize_base(getattr(current_user, 'base_code', 'SDA9'))


def _session_scope():
    if not has_request_context():
        return None, None
    role = flask_session.get('e18_role')
    base = flask_session.get('e18_base')
    return role, normalize_base(base) if base else None


def _scoped_execute(execute_state):
    if not execute_state.is_select or not has_request_context():
        return
    if getattr(g, '_enterprise18_loading_user', False):
        return
    if not flask_session.get('_user_id'):
        return
    role, base = _session_scope()
    if not role or role in ('ADMIN', 'ADMIN_GLOBAL') or not base:
        return
    statement = execute_state.statement
    for model in SCOPED_MODELS:
        statement = statement.options(
            with_loader_criteria(model, lambda cls, b=base: cls.base_code == b, include_aliases=True)
        )
    execute_state.statement = statement


def _object_base(obj, fallback):
    if isinstance(obj, Vehicle):
        driver = getattr(obj, 'driver', None)
        return normalize_base(getattr(driver, 'base_code', None) or fallback)
    if isinstance(obj, Expense):
        vehicle = getattr(obj, 'vehicle', None)
        creator = getattr(obj, 'created_by', None)
        return normalize_base(getattr(vehicle, 'base_code', None) or getattr(creator, 'base_code', None) or fallback)
    if isinstance(obj, DailyChecklist):
        vehicle = getattr(obj, 'vehicle', None)
        driver = getattr(obj, 'driver', None)
        return normalize_base(getattr(vehicle, 'base_code', None) or getattr(driver, 'base_code', None) or fallback)
    if isinstance(obj, OilChange):
        vehicle = getattr(obj, 'vehicle', None)
        return normalize_base(getattr(vehicle, 'base_code', None) or fallback)
    if isinstance(obj, StoredFile):
        uploader = getattr(obj, 'uploaded_by', None)
        return normalize_base(getattr(uploader, 'base_code', None) or fallback)
    if isinstance(obj, AdminNotification) and getattr(obj, 'checklist', None):
        return normalize_base(obj.checklist.base_code or fallback)
    return normalize_base(fallback)


def _assign_base(session, flush_context, instances):
    if not has_request_context() or not flask_session.get('_user_id'):
        return
    role, session_base = _session_scope()
    if role in ('ADMIN', 'ADMIN_GLOBAL'):
        requested = normalize_base(request.form.get('base_code') or request.args.get('base_code') or session_base or 'SDA9')
    else:
        requested = session_base or 'SDA9'
    for obj in session.new:
        if hasattr(obj, 'base_code'):
            obj.base_code = _object_base(obj, requested)


def install_multibase_events():
    global _EVENTS_INSTALLED
    if _EVENTS_INSTALLED:
        return
    event.listen(Session, 'do_orm_execute', _scoped_execute)
    event.listen(Session, 'before_flush', _assign_base)
    _EVENTS_INSTALLED = True


def _oil_status(vehicle):
    last_change = OilChange.query.filter_by(vehicle_id=vehicle.id).order_by(
        OilChange.change_date.desc(), OilChange.id.desc()
    ).first()
    if not last_change:
        return {
            'level': 'none', 'label': 'Sem troca registrada',
            'current_km': vehicle.current_km or 0, 'traveled': 0, 'remaining': 990
        }
    latest_checklist_km = db.session.query(func.max(DailyChecklist.odometer)).filter(
        DailyChecklist.vehicle_id == vehicle.id,
        DailyChecklist.is_deleted.is_(False),
        DailyChecklist.checklist_date >= last_change.change_date,
    ).scalar()
    current_km = max(vehicle.current_km or 0, latest_checklist_km or 0)
    traveled = max(0, current_km - last_change.odometer)
    remaining = 990 - traveled
    if remaining <= 0:
        level, label = 'danger', 'Troca de óleo vencida'
    elif remaining <= 190:
        level, label = 'warning', 'Próximo da troca'
    else:
        level, label = 'success', 'Óleo em dia'
    return {
        'level': level, 'label': label, 'current_km': current_km,
        'traveled': traveled, 'remaining': remaining, 'base_km': last_change.odometer
    }


def _driver_action_status(user):
    today = local_today()
    rows = DailyChecklist.query.filter_by(
        driver_id=user.id, checklist_date=today, is_deleted=False
    ).order_by(DailyChecklist.created_at.asc()).all()
    retiradas = [r for r in rows if r.checklist_type == 'RETIRADA']
    devolucoes = [r for r in rows if r.checklist_type == 'DEVOLUCAO']
    if not retiradas:
        return {
            'level': 'danger', 'title': 'Checklist de retirada pendente',
            'text': 'Faça o checklist antes de iniciar a operação.',
            'url': url_for('main.checklist_new', type='RETIRADA')
        }
    if len(devolucoes) < len(retiradas):
        return {
            'level': 'warning', 'title': 'Checklist de devolução pendente',
            'text': 'Ao finalizar o uso da moto, registre a devolução.',
            'url': url_for('main.checklist_new', type='DEVOLUCAO')
        }
    return {
        'level': 'success', 'title': 'Checklists do dia concluídos',
        'text': 'Retirada e devolução registradas.',
        'url': url_for('main.checklist_history')
    }


def enterprise18_context():
    if not getattr(current_user, 'is_authenticated', False):
        return {'e18': None}
    data = {
        'base': current_base(), 'is_global': is_global_admin(),
        'is_base_admin': is_base_admin(), 'bases': BASES
    }
    if current_user.role == 'DRIVER':
        data['driver_action'] = _driver_action_status(current_user)
        vehicle = current_user.vehicle
        data['oil'] = _oil_status(vehicle) if vehicle and vehicle.vehicle_type == 'MOTORCYCLE' else None
    elif current_user.is_admin:
        vehicles = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE').order_by(Vehicle.plate).all()
        statuses = [{'vehicle': v, **_oil_status(v)} for v in vehicles]
        today = local_today()
        drivers = User.query.filter_by(role='DRIVER', active=True).all()
        data['fleet'] = {
            'total': len(statuses),
            'danger': sum(1 for s in statuses if s['level'] == 'danger'),
            'warning': sum(1 for s in statuses if s['level'] == 'warning'),
            'none': sum(1 for s in statuses if s['level'] == 'none'),
            'success': sum(1 for s in statuses if s['level'] == 'success'),
            'retirada_pendente': sum(
                1 for d in drivers
                if not DailyChecklist.query.filter_by(
                    driver_id=d.id, checklist_date=today,
                    checklist_type='RETIRADA', is_deleted=False
                ).first()
            ),
        }
    return {'e18': data}


def _admin_required():
    if not current_user.is_admin:
        abort(403)


@enterprise18_bp.route('/admin/users/<int:user_id>/edit', methods=['POST'])
@login_required
def edit_user(user_id):
    _admin_required()
    user = db.session.get(User, user_id) or abort(404)
    if is_base_admin() and user.base_code != current_base():
        abort(403)
    try:
        name = (request.form.get('name') or '').strip()
        username = (request.form.get('username') or '').strip()
        if not name or not username:
            raise ValueError('Nome e login são obrigatórios.')
        duplicate = User.query.filter(User.username == username, User.id != user.id).first()
        if duplicate:
            raise ValueError('Este login já está sendo utilizado.')
        old_name = user.name
        user.name = name
        user.username = username
        user.email = (request.form.get('email') or '').strip() or None
        user.phone = (request.form.get('phone') or '').strip() or None
        user.active = request.form.get('active') == 'on'
        if is_global_admin():
            role = request.form.get('role', user.role)
            if role not in ('DRIVER', 'ADMIN_BASE', 'ADMIN', 'ADMIN_GLOBAL'):
                raise ValueError('Perfil inválido.')
            user.role = role
            user.base_code = normalize_base(request.form.get('base_code') or user.base_code)
        db.session.add(AuditLog(
            action='EDIT_USER', entity_type='USER', entity_id=user.id,
            description=f'Cadastro atualizado de {old_name} para {user.name}. Base: {user.base_code}.',
            user_id=current_user.id, base_code=user.base_code
        ))
        db.session.commit()
        flash('Usuário atualizado sem perder o histórico.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(url_for('main.users'))


@enterprise18_bp.route('/admin/checklist-report')
@login_required
def checklist_report():
    _admin_required()
    start_raw = request.args.get('start')
    end_raw = request.args.get('end')
    base_filter = normalize_base(request.args.get('base_code')) if request.args.get('base_code') else None
    q = db.session.query(
        User.id, User.name, User.base_code,
        func.count(DailyChecklist.id).label('total'),
        func.sum(case((DailyChecklist.checklist_type == 'RETIRADA', 1), else_=0)).label('retiradas'),
        func.sum(case((DailyChecklist.checklist_type == 'DEVOLUCAO', 1), else_=0)).label('devolucoes'),
        func.sum(case((DailyChecklist.has_damage.is_(True), 1), else_=0)).label('avarias'),
        func.sum(case((DailyChecklist.borrowed_vehicle.is_(True), 1), else_=0)).label('emprestadas'),
        func.max(DailyChecklist.checklist_date).label('ultimo'),
    ).join(DailyChecklist, DailyChecklist.driver_id == User.id).filter(
        DailyChecklist.is_deleted.is_(False)
    )
    if start_raw:
        q = q.filter(DailyChecklist.checklist_date >= datetime.strptime(start_raw, '%Y-%m-%d').date())
    if end_raw:
        q = q.filter(DailyChecklist.checklist_date <= datetime.strptime(end_raw, '%Y-%m-%d').date())
    if is_global_admin() and base_filter:
        q = q.filter(User.base_code == base_filter, DailyChecklist.base_code == base_filter)
    rows = q.group_by(User.id, User.name, User.base_code).order_by(User.name).all()
    if request.args.get('format') == 'csv':
        out = io.StringIO()
        writer = csv.writer(out, delimiter=';')
        writer.writerow(['Base','Motorista','Total','Retiradas','Devolucoes','Avarias','Moto emprestada','Ultimo checklist'])
        for r in rows:
            writer.writerow([
                r.base_code, r.name, r.total, r.retiradas or 0, r.devolucoes or 0,
                r.avarias or 0, r.emprestadas or 0,
                r.ultimo.strftime('%d/%m/%Y') if r.ultimo else ''
            ])
        return Response(
            '\ufeff' + out.getvalue(), mimetype='text/csv; charset=utf-8',
            headers={'Content-Disposition':'attachment; filename=relatorio_checklists.csv'}
        )
    return render_template(
        'admin/checklist_report.html', rows=rows, bases=BASES,
        start=start_raw or '', end=end_raw or '', base_filter=base_filter or ''
    )


def _phone(value):
    digits = ''.join(c for c in (value or '') if c.isdigit())
    return ('55' + digits) if len(digits) in (10,11) else digits


def _checklist_message(checklist):
    base_url = os.getenv('ONLINE_URL') or request.url_root.rstrip('/')
    share_url = f"{base_url}{url_for('main.checklist_share', token=checklist.share_token)}"
    action = 'devolução' if checklist.checklist_type == 'DEVOLUCAO' else 'retirada'
    return (
        f"FAVELA LLOG - Controle de Veículos\n\nChecklist de {action}\n"
        f"Motorista: {checklist.driver.name}\nBase: {checklist.base_code}\n"
        f"Moto: {checklist.vehicle.brand} {checklist.vehicle.model} - {checklist.vehicle.plate}\n"
        f"Data: {checklist.checklist_date.strftime('%d/%m/%Y')}\nKM: {checklist.odometer}\n\n"
        f"Checklist e imagens: {share_url}"
    )


def _cloud_send(phone, message):
    token = os.getenv('WHATSAPP_TOKEN')
    phone_number_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
    if not token or not phone_number_id:
        return False
    import json
    payload = json.dumps({
        'messaging_product':'whatsapp', 'to':phone, 'type':'text',
        'text':{'body':message}
    }).encode('utf-8')
    req = Request(
        f'https://graph.facebook.com/v22.0/{phone_number_id}/messages',
        data=payload,
        headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'},
        method='POST'
    )
    with urlopen(req, timeout=12) as response:
        return 200 <= response.status < 300


@enterprise18_bp.route('/checklist/<int:checklist_id>/send-driver-whatsapp', methods=['POST'])
@login_required
def send_driver_whatsapp(checklist_id):
    checklist = db.session.get(DailyChecklist, checklist_id) or abort(404)
    if not current_user.is_admin and checklist.driver_id != current_user.id:
        abort(403)
    if is_base_admin() and checklist.base_code != current_base():
        abort(403)
    phone = _phone(checklist.driver.phone)
    if not phone:
        flash('O motorista não possui WhatsApp cadastrado.', 'danger')
        return redirect(url_for('main.checklist_detail', checklist_id=checklist.id))
    message = _checklist_message(checklist)
    try:
        if _cloud_send(phone, message):
            checklist.whatsapp_sent_at = utc_now()
            checklist.whatsapp_confirmed_by_id = current_user.id
            db.session.commit()
            flash('Checklist enviado diretamente para o WhatsApp do motorista.', 'success')
            return redirect(url_for('main.checklist_detail', checklist_id=checklist.id))
    except Exception:
        db.session.rollback()
    # Sem API oficial configurada, abre a conversa correta. Não marca como enviado
    # porque o sistema não pode afirmar que o usuário realmente apertou Enviar.
    return redirect(f'https://wa.me/{phone}?text={quote(message)}')


def init_enterprise18(app):
    install_multibase_events()

    @app.before_request
    def _sync_enterprise18_session_and_guards():
        if current_user.is_authenticated:
            flask_session['e18_role'] = current_user.role
            flask_session['e18_base'] = current_user.base_code
        else:
            flask_session.pop('e18_role', None)
            flask_session.pop('e18_base', None)
            return

        # Garante que veículo e motorista nunca sejam vinculados entre bases.
        if request.method == 'POST' and request.endpoint in ('main.vehicles', 'main.edit_vehicle'):
            target_base = normalize_base(
                request.form.get('base_code') if is_global_admin() else current_user.base_code
            )
            driver_id = request.form.get('driver_id', type=int)
            if driver_id:
                driver = db.session.get(User, driver_id)
                if not driver or driver.role != 'DRIVER' or driver.base_code != target_base:
                    flash('O motorista selecionado não pertence à mesma base do veículo.', 'danger')
                    return redirect(url_for('main.vehicles'))
            if request.endpoint == 'main.edit_vehicle' and is_global_admin():
                vehicle_id = (request.view_args or {}).get('vehicle_id')
                vehicle = db.session.get(Vehicle, vehicle_id) if vehicle_id else None
                if vehicle:
                    vehicle.base_code = target_base

    app.register_blueprint(enterprise18_bp)
    app.context_processor(enterprise18_context)
