from datetime import timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user

from .models import db, User, Vehicle, VehicleUseRequest
from .time_utils import utc_now

wait_bp = Blueprint('enterprise19_wait', __name__)


def _plate(value):
    return ''.join(c for c in (value or '').upper() if c.isalnum())[:10]


def _clear_pending():
    session.pop('pending_vehicle_use_request_id', None)
    session.pop('pending_vehicle_use_user_id', None)


def login_with_wait():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    if request.method != 'POST':
        if session.get('pending_vehicle_use_request_id') and session.get('pending_vehicle_use_user_id'):
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
    approved = VehicleUseRequest.query.filter_by(requester_id=user.id, vehicle_id=vehicle.id, status='APPROVED').order_by(VehicleUseRequest.decided_at.desc()).first()
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
        return render_template('auth/login.html', need_justification=True, owner_name=owner_name, plate_value=plate_value, username_value=username)

    pending = VehicleUseRequest.query.filter_by(requester_id=user.id, vehicle_id=vehicle.id, status='PENDING').order_by(VehicleUseRequest.requested_at.desc()).first()
    if not pending:
        pending = VehicleUseRequest(requester_id=user.id, vehicle_id=vehicle.id, owner_driver_id=vehicle.driver_id, justification=justification, base_code=user.base_code, status='PENDING')
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


@wait_bp.get('/aguardando-autorizacao/cancelar')
def cancel_vehicle_use_wait():
    _clear_pending()
    session.pop('active_vehicle_id', None)
    session.pop('active_vehicle_justification', None)
    return redirect(url_for('auth.login'))


def init_enterprise19_wait(app):
    app.register_blueprint(wait_bp)
    app.view_functions['auth.login'] = login_with_wait
