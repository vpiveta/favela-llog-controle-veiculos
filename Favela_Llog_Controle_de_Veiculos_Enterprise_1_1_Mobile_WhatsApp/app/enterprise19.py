import io
import json
from datetime import timedelta
from flask import Blueprint, abort, flash, has_request_context, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_user, login_required
from sqlalchemy import event
from sqlalchemy.orm import Session
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from .models import db, User, Vehicle, Expense, DailyChecklist, VehicleUseRequest, VehicleIssue, AuditLog
from .time_utils import utc_now

enterprise19_bp = Blueprint('enterprise19', __name__)
ITEMS = [
    ('tires_ok','Pneus'),('brakes_ok','Freios'),('lights_ok','Luzes'),('indicators_ok','Setas'),
    ('mirrors_ok','Retrovisores'),('horn_ok','Buzina'),('chain_ok','Corrente'),('charger_ok','Carregador'),
    ('phone_holder_ok','Suporte de celular'),('top_case_ok','Baú'),('saddlebags_ok','Alforje')
]
_EVENTS = False

def _plate(value):
    return ''.join(c for c in (value or '').upper() if c.isalnum())[:10]

def active_vehicle():
    vid = session.get('active_vehicle_id')
    if not vid or not current_user.is_authenticated:
        return None
    vehicle = db.session.get(Vehicle, int(vid))
    if not vehicle or vehicle.vehicle_type != 'MOTORCYCLE':
        return None
    if not current_user.is_global_admin and vehicle.base_code != current_user.base_code:
        return None
    return vehicle

def _login_view():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    plate_value = ''
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        plate_value = _plate(request.form.get('plate'))
        user = User.query.filter_by(username=username).first()
        if not user or not user.active or not user.check_password(password):
            flash('Usuário ou senha inválidos.', 'danger')
            return render_template('auth/login.html', need_justification=False, plate_value=plate_value, username_value=username)
        if user.is_admin:
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
            login_user(user)
            session['active_vehicle_id'] = vehicle.id
            session['active_vehicle_justification'] = ''
            return redirect(url_for('main.dashboard'))
        owner_name = vehicle.driver.name if vehicle.driver else 'outro motorista'
        approved = VehicleUseRequest.query.filter_by(requester_id=user.id, vehicle_id=vehicle.id, status='APPROVED').order_by(VehicleUseRequest.decided_at.desc()).first()
        if approved and approved.decided_at and approved.decided_at >= utc_now() - timedelta(hours=24):
            approved.status = 'USED'
            db.session.commit()
            login_user(user)
            session['active_vehicle_id'] = vehicle.id
            session['active_vehicle_justification'] = approved.justification
            return redirect(url_for('main.dashboard'))
        justification = (request.form.get('justification') or '').strip()
        if not justification:
            flash(f'A moto {vehicle.plate} está vinculada a {owner_name}. Informe a justificativa para solicitar autorização.', 'warning')
            return render_template('auth/login.html', need_justification=True, owner_name=owner_name, plate_value=plate_value, username_value=username)
        pending = VehicleUseRequest.query.filter_by(requester_id=user.id, vehicle_id=vehicle.id, status='PENDING').first()
        if not pending:
            db.session.add(VehicleUseRequest(requester_id=user.id, vehicle_id=vehicle.id, owner_driver_id=vehicle.driver_id, justification=justification, base_code=user.base_code, status='PENDING'))
            db.session.commit()
        flash('Solicitação enviada ao gerente. Após a aprovação, entre novamente com a mesma placa.', 'warning')
        return render_template('auth/login.html', need_justification=True, owner_name=owner_name, plate_value=plate_value, username_value=username)
    return render_template('auth/login.html', need_justification=False, plate_value='')

@enterprise19_bp.post('/admin/vehicle-use/<int:req_id>/<decision>')
@login_required
def decide_vehicle_use(req_id, decision):
    if not current_user.is_admin:
        abort(403)
    row = db.session.get(VehicleUseRequest, req_id) or abort(404)
    if current_user.is_base_admin and row.base_code != current_user.base_code:
        abort(403)
    if decision not in ('approve','deny'):
        abort(400)
    row.status = 'APPROVED' if decision == 'approve' else 'DENIED'
    row.decided_at = utc_now()
    row.decided_by_id = current_user.id
    db.session.add(AuditLog(action='VEHICLE_USE_DECISION', entity_type='VEHICLE_USE_REQUEST', entity_id=row.id, description=f"Solicitação de {row.requester.name} para {row.vehicle.plate}: {row.status}.", user_id=current_user.id, base_code=row.base_code))
    db.session.commit()
    flash('Solicitação atualizada.', 'success')
    return redirect(request.referrer or url_for('main.dashboard'))

@enterprise19_bp.get('/issue/<int:issue_id>/maintenance')
@login_required
def issue_maintenance(issue_id):
    issue = db.session.get(VehicleIssue, issue_id) or abort(404)
    if not current_user.is_global_admin and issue.base_code != current_user.base_code:
        abort(403)
    if issue.status != 'OPEN':
        flash('Esta pendência já foi solucionada.', 'warning')
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('main.maintenance_new', vehicle_id=issue.vehicle_id, issue_id=issue.id))

def _before_flush(sess, flush_context, instances):
    if not has_request_context():
        return
    for obj in list(sess.new):
        if isinstance(obj, Expense):
            vehicle = obj.vehicle or (db.session.get(Vehicle, obj.vehicle_id) if obj.vehicle_id else None)
            if vehicle:
                obj.responsible_driver_id = vehicle.driver_id
            issue_id = request.form.get('issue_id', type=int) if request.method == 'POST' else None
            if issue_id and obj.expense_type == 'MAINTENANCE':
                issue = db.session.get(VehicleIssue, issue_id)
                if issue and issue.status == 'OPEN' and issue.vehicle_id == obj.vehicle_id:
                    issue.status = 'RESOLVED'
                    issue.resolved_at = utc_now()
                    issue.resolved_by_id = current_user.id if current_user.is_authenticated else obj.created_by_id
                    issue.maintenance_expense = obj
        elif isinstance(obj, DailyChecklist) and request.method == 'POST':
            attention = {}
            for field, label in ITEMS:
                if request.form.get(field) == 'attention':
                    reason = (request.form.get(field + '_reason') or '').strip()
                    if reason:
                        attention[field] = {'label': label, 'reason': reason}
            if request.form.get('general_condition') in ('ATTENTION','MAINTENANCE'):
                reason = (request.form.get('general_condition_reason') or '').strip()
                if reason:
                    attention['general_condition'] = {'label':'Estado geral','reason':reason}
            obj.attention_notes = json.dumps(attention, ensure_ascii=False) if attention else None
            for code, info in attention.items():
                sess.add(VehicleIssue(vehicle=obj.vehicle, checklist=obj, reported_by_id=obj.driver_id, item_code=code, item_label=info['label'], description=info['reason'], base_code=obj.base_code or getattr(obj.vehicle,'base_code','SDA9')))

def _selected_vehicle(prefer_active_checklist=False):
    from .routes import active_checklist_for_driver
    vehicle_id = request.form.get('motorcycle_vehicle_id', type=int) or request.form.get('vehicle_id', type=int) or request.args.get('vehicle_id', type=int)
    if vehicle_id:
        v = db.session.get(Vehicle, vehicle_id)
        if v and v.vehicle_type == 'MOTORCYCLE' and (current_user.is_global_admin or v.base_code == current_user.base_code):
            return v
    if prefer_active_checklist and not current_user.is_admin:
        row = active_checklist_for_driver(current_user)
        if row:
            return row.vehicle
    v = active_vehicle()
    if v:
        return v
    return current_user.vehicle if current_user.vehicle and current_user.vehicle.vehicle_type == 'MOTORCYCLE' else None

def _context():
    if not current_user.is_authenticated:
        return {}
    v = active_vehicle()
    all_base_motorcycles = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE').order_by(Vehicle.plate).all()
    pending_requests = []
    owner_requests = []
    if current_user.is_admin:
        q = VehicleUseRequest.query.filter_by(status='PENDING')
        if current_user.is_base_admin:
            q = q.filter_by(base_code=current_user.base_code)
        pending_requests = q.order_by(VehicleUseRequest.requested_at.desc()).all()
    elif current_user.role == 'DRIVER':
        owner_requests = VehicleUseRequest.query.filter(VehicleUseRequest.owner_driver_id == current_user.id, VehicleUseRequest.status.in_(('APPROVED','USED'))).order_by(VehicleUseRequest.requested_at.desc()).limit(3).all()
    open_issues = VehicleIssue.query.filter_by(vehicle_id=v.id, status='OPEN').order_by(VehicleIssue.created_at.desc()).all() if v else []
    last_fuel = last_maintenance = None
    temporary = bool(v and current_user.role == 'DRIVER' and v.driver_id and v.driver_id != current_user.id)
    if temporary:
        last_fuel = Expense.query.filter_by(vehicle_id=v.id, expense_type='FUEL', is_deleted=False).order_by(Expense.expense_date.desc(), Expense.id.desc()).first()
        last_maintenance = Expense.query.filter_by(vehicle_id=v.id, expense_type='MAINTENANCE', is_deleted=False).order_by(Expense.expense_date.desc(), Expense.id.desc()).first()
    return {'active_vehicle': v, 'active_vehicle_temporary': temporary, 'active_vehicle_justification': session.get('active_vehicle_justification',''), 'active_vehicle_last_fuel': last_fuel, 'active_vehicle_last_maintenance': last_maintenance, 'active_vehicle_issues': open_issues, 'vehicle_use_pending': pending_requests, 'vehicle_owner_use_alerts': owner_requests, 'maintenance_issue_id': request.args.get('issue_id', type=int), 'all_base_motorcycles': all_base_motorcycles}

def _money(v): return f"R$ {float(v or 0):.2f}".replace('.', ',')

def _pdf_response(title, rows, filename):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=14*mm, leftMargin=14*mm, topMargin=14*mm, bottomMargin=14*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CenterTitle', parent=styles['Title'], alignment=TA_CENTER, textColor=colors.HexColor('#111827')))
    story = [Paragraph('FAVELA LLOG', styles['CenterTitle']), Paragraph(title, styles['Heading2']), Spacer(1, 5*mm)]
    data = [[Paragraph('<b>Campo</b>', styles['BodyText']), Paragraph('<b>Informação</b>', styles['BodyText'])]]
    for a,b in rows:
        data.append([Paragraph(str(a), styles['BodyText']), Paragraph(str(b or '-').replace('\n','<br/>'), styles['BodyText'])])
    table = Table(data, colWidths=[55*mm, 115*mm], repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#f4b000')),('TEXTCOLOR',(0,0),(-1,0),colors.black),('GRID',(0,0),(-1,-1),0.4,colors.HexColor('#d1d5db')),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),6)]))
    story.append(table)
    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=False, download_name=filename)

@enterprise19_bp.get('/checklist/<int:checklist_id>/pdf')
@login_required
def checklist_pdf(checklist_id):
    c = db.session.get(DailyChecklist, checklist_id) or abort(404)
    if not current_user.is_admin and c.driver_id != current_user.id and c.owner_driver_id != current_user.id:
        abort(403)
    notes = json.loads(c.attention_notes) if c.attention_notes else {}
    item_rows = []
    for field,label in ITEMS:
        item_rows.append((label, 'OK' if getattr(c, field) else 'ATENÇÃO' + (f" - {notes.get(field,{}).get('reason')}" if field in notes else '')))
    rows = [('Base', c.base_code), ('Tipo', 'Devolução' if c.checklist_type=='DEVOLUCAO' else 'Retirada'), ('Data', c.checklist_date.strftime('%d/%m/%Y')), ('Motorista que utilizou', c.driver.name), ('Responsável da moto', c.owner_driver.name if c.owner_driver else 'Sem motorista cadastrado'), ('Moto', f'{c.vehicle.brand} {c.vehicle.model} - {c.vehicle.plate}'), ('KM', f'{c.odometer} km'), ('Uso temporário', 'Sim' if c.borrowed_vehicle else 'Não'), ('Justificativa', c.borrow_reason or '-')] + item_rows + [('Estado geral', c.general_condition), ('Avaria', c.damage_description if c.has_damage else 'Não informada')]
    return _pdf_response('Checklist da motocicleta', rows, f'checklist-{c.vehicle.plate}-{c.id}.pdf')

@enterprise19_bp.get('/expense/<int:expense_id>/pdf')
@login_required
def expense_pdf(expense_id):
    e = db.session.get(Expense, expense_id) or abort(404)
    if not current_user.is_admin and e.created_by_id != current_user.id and e.responsible_driver_id != current_user.id:
        abort(403)
    kind = 'Abastecimento' if e.expense_type == 'FUEL' else 'Manutenção'
    rows = [('Base', e.base_code), ('Tipo', kind), ('Data', e.expense_date.strftime('%d/%m/%Y')), ('Veículo', f'{e.vehicle.brand} {e.vehicle.model} - {e.vehicle.plate}'), ('KM', f'{e.odometer or 0} km'), ('Motorista responsável', e.responsible_driver.name if e.responsible_driver else 'Sem motorista cadastrado'), ('Lançado por', e.created_by.name), ('Valor', _money(e.amount))]
    if e.fuel:
        rows += [('Litros', str(e.fuel.liters or '-')), ('Combustível', e.fuel.fuel_type or 'Gasolina'), ('Posto', e.fuel.station or '-')]
    if e.maintenance:
        rows += [('Descrição', e.maintenance.description), ('Oficina', e.maintenance.workshop or '-'), ('Status', e.maintenance.status), ('Inclui troca de óleo', 'Sim' if e.maintenance.is_oil_change else 'Não'), ('Valor do óleo', _money(e.maintenance.oil_amount) if e.maintenance.oil_amount else '-')]
    if e.notes:
        rows.append(('Observação', e.notes))
    return _pdf_response(kind, rows, f'{kind.lower()}-{e.vehicle.plate}-{e.id}.pdf')

def init_enterprise19(app):
    global _EVENTS
    from . import routes
    routes.selected_vehicle = _selected_vehicle
    app.view_functions['auth.login'] = _login_view
    if not _EVENTS:
        event.listen(Session, 'before_flush', _before_flush)
        _EVENTS = True
    app.register_blueprint(enterprise19_bp)
    app.context_processor(_context)
