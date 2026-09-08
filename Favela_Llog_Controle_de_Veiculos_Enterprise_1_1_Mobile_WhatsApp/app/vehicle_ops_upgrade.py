from datetime import datetime
from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for, has_request_context
from flask_login import current_user, login_required
from sqlalchemy import event
from sqlalchemy.orm import Session

from .models import db, User, Vehicle, VehicleIssue, Expense, DailyChecklist, AuditLog
from .time_utils import local_today, utc_now

ops_bp = Blueprint('vehicle_ops', __name__)


class OdometerAdjustment(db.Model):
    __tablename__ = 'odometer_adjustment'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False, index=True)
    informed_driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    old_km = db.Column(db.Integer, nullable=False)
    new_km = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    base_code = db.Column(db.String(10), nullable=False, default='SDA9', index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    vehicle = db.relationship('Vehicle')
    informed_driver = db.relationship('User', foreign_keys=[informed_driver_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])


def _vehicles_scope():
    q = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE').order_by(Vehicle.plate)
    if not current_user.is_global_admin:
        q = q.filter_by(base_code=current_user.base_code)
    return q.all()


def _drivers_scope():
    q = User.query.filter_by(role='DRIVER', active=True).order_by(User.name)
    if not current_user.is_global_admin:
        q = q.filter_by(base_code=current_user.base_code)
    return q.all()


def _can_manage_vehicle(vehicle):
    if not current_user.is_admin:
        return False
    return current_user.is_global_admin or vehicle.base_code == current_user.base_code


@ops_bp.post('/moto/<int:vehicle_id>/status')
@login_required
def vehicle_status(vehicle_id):
    vehicle = db.session.get(Vehicle, vehicle_id) or abort(404)
    if vehicle.vehicle_type != 'MOTORCYCLE' or not _can_manage_vehicle(vehicle):
        abort(403)
    new_status = (request.form.get('status') or '').upper().strip()
    if new_status not in {'AVAILABLE', 'MAINTENANCE', 'BLOCKED'}:
        flash('Status inválido.', 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))
    old_status = vehicle.status
    vehicle.status = new_status
    db.session.add(AuditLog(
        action='VEHICLE_STATUS', entity_type='VEHICLE', entity_id=vehicle.id,
        description=f'Status da moto {vehicle.plate} alterado de {old_status} para {new_status}.',
        base_code=vehicle.base_code, user_id=current_user.id,
    ))
    db.session.commit()
    flash(f'Status da moto {vehicle.plate} atualizado.', 'success')
    return redirect(request.referrer or url_for('main.dashboard'))


@ops_bp.get('/moto/<int:vehicle_id>/historico-completo')
@login_required
def vehicle_full_history(vehicle_id):
    vehicle = db.session.get(Vehicle, vehicle_id) or abort(404)
    if vehicle.vehicle_type != 'MOTORCYCLE':
        abort(404)
    if not current_user.is_global_admin and vehicle.base_code != current_user.base_code:
        abort(403)
    if not current_user.is_admin and (not current_user.vehicle or current_user.vehicle.id != vehicle.id):
        abort(403)

    expenses = Expense.query.filter(
        Expense.vehicle_id == vehicle.id,
        Expense.asset_type == 'MOTORCYCLE',
        Expense.is_deleted.is_(False),
    ).order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    uses = DailyChecklist.query.filter(
        DailyChecklist.vehicle_id == vehicle.id,
        DailyChecklist.is_deleted.is_(False),
    ).order_by(DailyChecklist.checklist_date.desc(), DailyChecklist.created_at.desc()).all()
    total = sum((Decimal(e.amount) for e in expenses), Decimal('0'))
    fuel = sum((Decimal(e.amount) for e in expenses if e.expense_type == 'FUEL'), Decimal('0'))
    maintenance = sum((Decimal(e.amount) for e in expenses if e.expense_type == 'MAINTENANCE'), Decimal('0'))
    from .enterprise19_wait import get_driver_cnh
    return render_template(
        'vehicle_history.html', vehicle=vehicle, month='', month_label='todo o histórico',
        expenses=expenses, uses=uses, total=total, fuel=fuel, maintenance=maintenance,
        owner_cnh=get_driver_cnh(vehicle.driver_id) if vehicle.driver_id else None,
        all_history=True,
    )


@ops_bp.route('/km/atualizar', methods=['GET', 'POST'])
@login_required
def update_km():
    vehicles = _vehicles_scope()
    drivers = _drivers_scope()
    if request.method == 'POST':
        try:
            vehicle = db.session.get(Vehicle, request.form.get('vehicle_id', type=int))
            if not vehicle or vehicle.vehicle_type != 'MOTORCYCLE':
                raise ValueError('Selecione uma moto válida.')
            if not current_user.is_global_admin and vehicle.base_code != current_user.base_code:
                abort(403)
            driver_id = request.form.get('driver_id', type=int)
            driver = db.session.get(User, driver_id) if driver_id else None
            if driver and (driver.role != 'DRIVER' or (not current_user.is_global_admin and driver.base_code != current_user.base_code)):
                raise ValueError('Motorista inválido para esta base.')
            new_km = request.form.get('new_km', type=int)
            if new_km is None or new_km < 0:
                raise ValueError('Informe um KM válido.')
            reason = (request.form.get('reason') or '').strip()
            if not reason:
                raise ValueError('Informe o motivo/origem da atualização de KM.')
            old_km = int(vehicle.current_km or 0)
            vehicle.current_km = new_km
            row = OdometerAdjustment(
                vehicle_id=vehicle.id, informed_driver_id=driver.id if driver else None,
                old_km=old_km, new_km=new_km, reason=reason,
                base_code=vehicle.base_code, created_by_id=current_user.id,
            )
            db.session.add(row)
            db.session.add(AuditLog(
                action='ODOMETER_ADJUSTMENT', entity_type='VEHICLE', entity_id=vehicle.id,
                description=f'KM da moto {vehicle.plate} alterado de {old_km} para {new_km}. Informado por: {driver.name if driver else "não informado"}. Motivo: {reason}',
                base_code=vehicle.base_code, user_id=current_user.id,
            ))
            db.session.commit()
            flash(f'KM da moto {vehicle.plate} atualizado para {new_km} km.', 'success')
            return redirect(url_for('vehicle_ops.update_km'))
        except Exception as exc:
            db.session.rollback()
            if getattr(exc, 'code', None) == 403:
                raise
            flash(str(exc), 'danger')
    history_q = OdometerAdjustment.query.order_by(OdometerAdjustment.created_at.desc())
    if not current_user.is_global_admin:
        history_q = history_q.filter_by(base_code=current_user.base_code)
    return render_template('odometer_update.html', vehicles=vehicles, drivers=drivers, history=history_q.limit(50).all())


@ops_bp.route('/pendencia/<int:issue_id>/manutencao', methods=['GET', 'POST'])
@login_required
def issue_action(issue_id):
    issue = db.session.get(VehicleIssue, issue_id) or abort(404)
    if not current_user.is_global_admin and issue.base_code != current_user.base_code:
        abort(403)
    if issue.status == 'RESOLVED':
        flash('Esta pendência já foi solucionada.', 'warning')
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        action = (request.form.get('action') or '').upper()
        note = (request.form.get('note') or '').strip()
        if action in {'SCHEDULED', 'AUTHORIZED'}:
            issue.status = action
            label = 'manutenção agendada' if action == 'SCHEDULED' else 'manutenção autorizada'
            db.session.add(AuditLog(
                action='VEHICLE_ISSUE_STATUS', entity_type='VEHICLE_ISSUE', entity_id=issue.id,
                description=f'Pendência {issue.item_label} da moto {issue.vehicle.plate}: {label}. {note}',
                base_code=issue.base_code, user_id=current_user.id,
            ))
            db.session.commit()
            flash('Pendência atualizada.', 'success')
            return redirect(url_for('main.dashboard'))
        if action == 'REGISTER':
            return redirect(url_for('main.maintenance_new', vehicle_id=issue.vehicle_id, issue_id=issue.id))
        flash('Selecione uma ação.', 'danger')
    return render_template('issue_maintenance_action.html', issue=issue)


@ops_bp.get('/manutencao/<int:expense_id>')
@login_required
def maintenance_detail(expense_id):
    expense = db.session.get(Expense, expense_id) or abort(404)
    if expense.is_deleted or expense.expense_type != 'MAINTENANCE' or not expense.maintenance:
        abort(404)
    if not current_user.is_global_admin and expense.base_code != current_user.base_code:
        abort(403)
    if not current_user.is_admin:
        allowed = expense.created_by_id == current_user.id or expense.responsible_driver_id == current_user.id
        if not allowed:
            abort(403)
    linked_issues = VehicleIssue.query.filter_by(maintenance_expense_id=expense.id).all()
    return render_template('maintenance_detail.html', expense=expense, linked_issues=linked_issues)


def _resolve_linked_issue_after_maintenance(sess, flush_context, instances):
    if not has_request_context() or request.method != 'POST':
        return
    issue_id = request.form.get('issue_id', type=int)
    if not issue_id:
        return
    issue = db.session.get(VehicleIssue, issue_id)
    if not issue or issue.status not in {'OPEN', 'SCHEDULED', 'AUTHORIZED'}:
        return
    for obj in list(sess.new):
        if isinstance(obj, Expense) and obj.expense_type == 'MAINTENANCE' and obj.vehicle_id == issue.vehicle_id:
            issue.status = 'RESOLVED'
            issue.resolved_at = utc_now()
            issue.resolved_by_id = current_user.id if current_user.is_authenticated else obj.created_by_id
            issue.maintenance_expense = obj
            break


def init_vehicle_ops_upgrade(app):
    app.register_blueprint(ops_bp)
    app.view_functions['enterprise19.issue_maintenance'] = lambda issue_id: redirect(url_for('vehicle_ops.issue_action', issue_id=issue_id))
    event.listen(Session, 'before_flush', _resolve_linked_issue_after_maintenance)

    @app.after_request
    def inject_km_link(response):
        if response.mimetype != 'text/html' or not current_user.is_authenticated:
            return response
        try:
            html = response.get_data(as_text=True)
            if 'Atualizar KM' not in html and '</nav>' in html:
                html = html.replace('</nav>', f'<a href="{url_for("vehicle_ops.update_km")}">🧭 Atualizar KM</a></nav>', 1)
                response.set_data(html)
        except Exception:
            pass
        return response
