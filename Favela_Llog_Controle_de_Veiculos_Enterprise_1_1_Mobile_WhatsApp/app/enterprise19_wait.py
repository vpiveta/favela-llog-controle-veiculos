from datetime import timedelta
import json

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, login_required

from .models import db, User, Vehicle, VehicleUseRequest, DailyChecklist, Expense
from .time_utils import utc_now

wait_bp = Blueprint('enterprise19_wait', __name__)


class DriverDocument(db.Model):
    __tablename__ = 'driver_document'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True, index=True)
    cnh_number = db.Column(db.String(20), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    user = db.relationship('User')


def _plate(value):
    return ''.join(c for c in (value or '').upper() if c.isalnum())[:10]


def _cnh(value):
    return ''.join(c for c in (value or '') if c.isdigit())


def get_driver_cnh(user_id):
    if not user_id:
        return None
    row = DriverDocument.query.filter_by(user_id=user_id).first()
    return row.cnh_number if row else None


def _clear_pending():
    session.pop('pending_vehicle_use_request_id', None)
    session.pop('pending_vehicle_use_user_id', None)


def login_with_wait():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method != 'POST':
        pending_id = session.get('pending_vehicle_use_request_id')
        pending_user = session.get('pending_vehicle_use_user_id')
        if pending_id and pending_user:
            return redirect(url_for('enterprise19_wait.vehicle_use_wait'))
        return render_template('auth/login.html', need_justification=False, plate_value='')

    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    plate_value = _plate(request.form.get('plate'))
    user = User.query.filter_by(username=username).first()

    if not user or not user.active or not user.check_password(password):
        _clear_pending()
        flash('Usuário ou senha inválidos.', 'danger')
        return render_template('auth/login.html', need_justification=False, plate_value=plate_value, username_value=username)

    if user.is_admin:
        _clear_pending()
        login_user(user)
        session.pop('active_vehicle_id', None)
        session.pop('active_vehicle_justification', None)
        return redirect(url_for('main.dashboard'))

    if not plate_value:
        flash('Informe a placa da moto que será utilizada.', 'danger')
        return render_template('auth/login.html', need_justification=False, plate_value=plate_value, username_value=username)

    vehicle = Vehicle.query.filter_by(plate=plate_value, vehicle_type='MOTORCYCLE').first()
    if not vehicle or vehicle.base_code != user.base_code:
        flash('Placa não encontrada na sua base.', 'danger')
        return render_template('auth/login.html', need_justification=False, plate_value=plate_value, username_value=username)

    if vehicle.status == 'BLOCKED':
        flash('Esta moto está bloqueada para uso. Procure o gerente da base.', 'danger')
        return render_template('auth/login.html', need_justification=False, plate_value=plate_value, username_value=username)

    if not vehicle.driver_id or vehicle.driver_id == user.id:
        _clear_pending()
        login_user(user)
        session['active_vehicle_id'] = vehicle.id
        session['active_vehicle_justification'] = ''
        return redirect(url_for('main.dashboard'))

    owner_name = vehicle.driver.name if vehicle.driver else 'outro motorista'

    approved = VehicleUseRequest.query.filter_by(
        requester_id=user.id, vehicle_id=vehicle.id, status='APPROVED'
    ).order_by(VehicleUseRequest.decided_at.desc()).first()
    if approved and approved.decided_at and approved.decided_at >= utc_now() - timedelta(hours=24):
        approved.status = 'USED'
        db.session.commit()
        _clear_pending()
        login_user(user)
        session['active_vehicle_id'] = vehicle.id
        session['active_vehicle_justification'] = approved.justification
        return redirect(url_for('main.dashboard'))

    justification = (request.form.get('justification') or '').strip()
    if not justification:
        flash(f'A moto {vehicle.plate} está vinculada a {owner_name}. Informe a justificativa para solicitar autorização.', 'warning')
        return render_template(
            'auth/login.html', need_justification=True, owner_name=owner_name,
            plate_value=plate_value, username_value=username
        )

    pending = VehicleUseRequest.query.filter_by(
        requester_id=user.id, vehicle_id=vehicle.id, status='PENDING'
    ).order_by(VehicleUseRequest.requested_at.desc()).first()
    if not pending:
        pending = VehicleUseRequest(
            requester_id=user.id, vehicle_id=vehicle.id, owner_driver_id=vehicle.driver_id,
            justification=justification, base_code=user.base_code, status='PENDING'
        )
        db.session.add(pending)
        db.session.commit()

    session['pending_vehicle_use_request_id'] = pending.id
    session['pending_vehicle_use_user_id'] = user.id
    session.pop('active_vehicle_id', None)
    session.pop('active_vehicle_justification', None)
    return redirect(url_for('enterprise19_wait.vehicle_use_wait'))


@wait_bp.get('/aguardando-autorizacao')
def vehicle_use_wait():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    request_id = session.get('pending_vehicle_use_request_id')
    user_id = session.get('pending_vehicle_use_user_id')
    if not request_id or not user_id:
        return redirect(url_for('auth.login'))
    row = db.session.get(VehicleUseRequest, int(request_id))
    if not row or row.requester_id != int(user_id):
        _clear_pending()
        return redirect(url_for('auth.login'))
    return render_template('auth/waiting_vehicle_authorization.html', request_row=row)


@wait_bp.get('/aguardando-autorizacao/status')
def vehicle_use_wait_status():
    if current_user.is_authenticated:
        return jsonify({'status': 'APPROVED', 'redirect': url_for('main.dashboard')})

    request_id = session.get('pending_vehicle_use_request_id')
    user_id = session.get('pending_vehicle_use_user_id')
    if not request_id or not user_id:
        return jsonify({'status': 'EXPIRED', 'redirect': url_for('auth.login')})

    row = db.session.get(VehicleUseRequest, int(request_id))
    user = db.session.get(User, int(user_id))
    if not row or not user or row.requester_id != user.id or not user.active:
        _clear_pending()
        return jsonify({'status': 'EXPIRED', 'redirect': url_for('auth.login')})

    if row.status == 'APPROVED':
        vehicle = db.session.get(Vehicle, row.vehicle_id)
        if not vehicle or vehicle.base_code != user.base_code or vehicle.status == 'BLOCKED':
            row.status = 'DENIED'
            db.session.commit()
            return jsonify({'status': 'DENIED', 'message': 'A moto não está mais disponível para uso.'})
        row.status = 'USED'
        db.session.commit()
        login_user(user)
        session['active_vehicle_id'] = vehicle.id
        session['active_vehicle_justification'] = row.justification
        _clear_pending()
        return jsonify({'status': 'APPROVED', 'redirect': url_for('main.dashboard')})

    if row.status == 'DENIED':
        return jsonify({'status': 'DENIED', 'message': 'O gerente da base não autorizou o uso desta moto.'})

    return jsonify({'status': 'PENDING'})


@wait_bp.route('/meu-cadastro/cnh', methods=['GET', 'POST'])
@login_required
def complete_cnh():
    if current_user.role != 'DRIVER':
        return redirect(url_for('main.dashboard'))
    existing = DriverDocument.query.filter_by(user_id=current_user.id).first()
    if existing and request.method == 'GET':
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        number = _cnh(request.form.get('cnh_number'))
        if len(number) != 11:
            flash('Informe os 11 números da CNH.', 'danger')
            return render_template('auth/complete_cnh.html', cnh_value=number)
        duplicate = DriverDocument.query.filter(DriverDocument.cnh_number == number, DriverDocument.user_id != current_user.id).first()
        if duplicate:
            flash('Esta CNH já está vinculada a outro motorista.', 'danger')
            return render_template('auth/complete_cnh.html', cnh_value=number)
        if existing:
            existing.cnh_number = number
        else:
            db.session.add(DriverDocument(user_id=current_user.id, cnh_number=number))
        db.session.commit()
        flash('CNH cadastrada com sucesso. Você não precisará informar novamente.', 'success')
        return redirect(url_for('main.dashboard'))
    return render_template('auth/complete_cnh.html', cnh_value='')


def _checklist_pdf_with_cnh(checklist_id):
    from .enterprise19 import _pdf_response, ITEMS
    c = db.session.get(DailyChecklist, checklist_id) or abort(404)
    if not current_user.is_admin and c.driver_id != current_user.id and c.owner_driver_id != current_user.id:
        abort(403)
    try:
        notes = json.loads(c.attention_notes) if c.attention_notes else {}
    except Exception:
        notes = {}
    item_rows = []
    for field, label in ITEMS:
        item_rows.append((label, 'OK' if getattr(c, field) else 'ATENÇÃO' + (f" - {notes.get(field,{}).get('reason')}" if field in notes else '')))
    rows = [
        ('Base', c.base_code),
        ('Tipo', 'Devolução' if c.checklist_type == 'DEVOLUCAO' else 'Retirada'),
        ('Data', c.checklist_date.strftime('%d/%m/%Y')),
        ('Motorista que utilizou', c.driver.name),
        ('CNH do motorista', get_driver_cnh(c.driver_id) or 'Não cadastrada'),
        ('Responsável da moto', c.owner_driver.name if c.owner_driver else 'Sem motorista cadastrado'),
        ('CNH do responsável', get_driver_cnh(c.owner_driver_id) or 'Não cadastrada' if c.owner_driver_id else '-'),
        ('Moto', f'{c.vehicle.brand} {c.vehicle.model} - {c.vehicle.plate}'),
        ('KM', f'{c.odometer} km'),
        ('Uso temporário', 'Sim' if c.borrowed_vehicle else 'Não'),
        ('Justificativa', c.borrow_reason or '-'),
    ] + item_rows + [
        ('Estado geral', c.general_condition),
        ('Avaria', c.damage_description if c.has_damage else 'Não informada'),
    ]
    return _pdf_response('Checklist da motocicleta', rows, f'checklist-{c.vehicle.plate}-{c.id}.pdf')


def _expense_pdf_with_cnh(expense_id):
    from .enterprise19 import _pdf_response, _money
    e = db.session.get(Expense, expense_id) or abort(404)
    if not current_user.is_admin and e.created_by_id != current_user.id and e.responsible_driver_id != current_user.id:
        abort(403)
    kind = 'Abastecimento' if e.expense_type == 'FUEL' else 'Manutenção'
    rows = [
        ('Base', e.base_code), ('Tipo', kind), ('Data', e.expense_date.strftime('%d/%m/%Y')),
        ('Veículo', f'{e.vehicle.brand} {e.vehicle.model} - {e.vehicle.plate}'), ('KM', f'{e.odometer or 0} km'),
        ('Motorista responsável', e.responsible_driver.name if e.responsible_driver else 'Sem motorista cadastrado'),
        ('CNH do responsável', get_driver_cnh(e.responsible_driver_id) or 'Não cadastrada' if e.responsible_driver_id else '-'),
        ('Lançado por', e.created_by.name), ('CNH de quem lançou', get_driver_cnh(e.created_by_id) or 'Não cadastrada'),
        ('Valor', _money(e.amount)),
    ]
    if e.fuel:
        rows += [('Litros', str(e.fuel.liters or '-')), ('Combustível', e.fuel.fuel_type or 'Gasolina'), ('Posto', e.fuel.station or '-')]
    if e.maintenance:
        rows += [('Descrição', e.maintenance.description), ('Oficina', e.maintenance.workshop or '-'), ('Status', e.maintenance.status), ('Inclui troca de óleo', 'Sim' if e.maintenance.is_oil_change else 'Não'), ('Valor do óleo', _money(e.maintenance.oil_amount) if e.maintenance.oil_amount else '-')]
    if e.notes:
        rows.append(('Observação', e.notes))
    return _pdf_response(kind, rows, f'{kind.lower()}-{e.vehicle.plate}-{e.id}.pdf')


def _driver_document_context():
    if not current_user.is_authenticated:
        return {}
    return {'driver_cnh': get_driver_cnh(current_user.id) if current_user.role == 'DRIVER' else None}


def init_enterprise19_wait(app):
    app.register_blueprint(wait_bp)
    app.view_functions['auth.login'] = login_with_wait
    app.view_functions['enterprise19.checklist_pdf'] = login_required(_checklist_pdf_with_cnh)
    app.view_functions['enterprise19.expense_pdf'] = login_required(_expense_pdf_with_cnh)
    app.context_processor(_driver_document_context)

    @app.before_request
    def require_driver_cnh_once():
        if not current_user.is_authenticated or current_user.role != 'DRIVER':
            return None
        allowed = {
            'enterprise19_wait.complete_cnh', 'auth.logout', 'static',
            'enterprise19_wait.vehicle_use_wait', 'enterprise19_wait.vehicle_use_wait_status'
        }
        if request.endpoint in allowed:
            return None
        if not DriverDocument.query.filter_by(user_id=current_user.id).first():
            return redirect(url_for('enterprise19_wait.complete_cnh'))
        return None

    @app.before_request
    def capture_admin_cnh_edit():
        if request.method != 'POST' or request.endpoint != 'enterprise18.edit_user':
            return None
        if not current_user.is_authenticated or not current_user.is_admin:
            return None
        user_id = (request.view_args or {}).get('user_id')
        user = db.session.get(User, user_id) if user_id else None
        if not user or user.role != 'DRIVER':
            return None
        raw = (request.form.get('cnh_number') or '').strip()
        if not raw:
            return None
        number = _cnh(raw)
        if len(number) != 11:
            flash('A CNH deve conter 11 números.', 'danger')
            return redirect(url_for('main.users'))
        duplicate = DriverDocument.query.filter(DriverDocument.cnh_number == number, DriverDocument.user_id != user.id).first()
        if duplicate:
            flash('Esta CNH já está vinculada a outro motorista.', 'danger')
            return redirect(url_for('main.users'))
        doc = DriverDocument.query.filter_by(user_id=user.id).first()
        if doc:
            doc.cnh_number = number
        else:
            db.session.add(DriverDocument(user_id=user.id, cnh_number=number))
        return None
