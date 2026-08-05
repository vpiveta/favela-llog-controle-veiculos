from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import wraps
from pathlib import Path
from io import BytesIO
import os, uuid, secrets
from urllib.parse import quote
from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, send_file, url_for, abort, jsonify
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename
from .models import db, User, Vehicle, Expense, FuelDetail, MaintenanceDetail, OilChange, AlertRecipient, StoredFile, DailyChecklist, AdminNotification

auth_bp = Blueprint('auth', __name__)
main_bp = Blueprint('main', __name__)
ALLOWED = {'png','jpg','jpeg','webp','pdf'}

def admin_required(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Acesso restrito ao administrador.', 'danger')
            return redirect(url_for('main.dashboard'))
        return fn(*a, **kw)
    return wrapped

def store_uploaded_file(file, category, entity_type, entity_id, images_only=False):
    if not file or not file.filename:
        raise ValueError('A foto ou comprovante é obrigatório.')
    ext = file.filename.rsplit('.',1)[-1].lower() if '.' in file.filename else ''
    allowed = {'png','jpg','jpeg','webp'} if images_only else ALLOWED
    if ext not in allowed:
        raise ValueError('Formato inválido. Use JPG, PNG, WEBP' + ('.' if images_only else ' ou PDF.'))
    data = file.read()
    if not data:
        raise ValueError('O arquivo enviado está vazio.')
    if len(data) > current_app.config.get('MAX_CONTENT_LENGTH', 8 * 1024 * 1024):
        raise ValueError('Arquivo muito grande.')
    token = uuid.uuid4().hex
    stored = StoredFile(
        token=token, original_name=secure_filename(file.filename) or f'{category}.{ext}',
        mime_type=file.mimetype or ('image/jpeg' if images_only else 'application/octet-stream'),
        file_size=len(data), category=category, entity_type=entity_type, entity_id=entity_id,
        uploaded_by_id=current_user.id, content=data
    )
    db.session.add(stored)
    return token

def save_receipt(file, expense_id):
    return store_uploaded_file(file, 'RECEIPT', 'EXPENSE', expense_id, images_only=False)

def selected_vehicle():
    if current_user.is_admin:
        vehicle_id = request.form.get('vehicle_id', type=int) or request.args.get('vehicle_id', type=int)
        return db.session.get(Vehicle, vehicle_id) if vehicle_id else None
    return current_user.vehicle

def add_admin_notification(notification_type, title, message, checklist_id=None):
    db.session.add(AdminNotification(
        notification_type=notification_type,
        title=title,
        message=message,
        checklist_id=checklist_id,
    ))

@auth_bp.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username','').strip()).first()
        if user and user.active and user.check_password(request.form.get('password','')):
            login_user(user)
            return redirect(url_for('main.dashboard'))
        flash('Usuário ou senha inválidos.', 'danger')
    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('auth.login'))

@main_bp.route('/')
@login_required
def dashboard():
    month_start = date.today().replace(day=1)
    q = Expense.query.filter(Expense.expense_date >= month_start)
    if not current_user.is_admin:
        q = q.filter(Expense.created_by_id == current_user.id)
    expenses = q.order_by(Expense.expense_date.desc()).all()
    total = sum((Decimal(e.amount) for e in expenses), Decimal('0'))
    fuel = sum((Decimal(e.amount) for e in expenses if e.expense_type == 'FUEL'), Decimal('0'))
    maint = total - fuel
    alerts = build_oil_alerts(current_user.vehicle.id if not current_user.is_admin and current_user.vehicle else None)
    vehicles = Vehicle.query.order_by(Vehicle.plate).all() if current_user.is_admin else ([current_user.vehicle] if current_user.vehicle else [])
    today_checklists = DailyChecklist.query.filter_by(checklist_date=date.today())
    if not current_user.is_admin:
        today_checklists = today_checklists.filter_by(driver_id=current_user.id)
    today_checklist_count = today_checklists.count()
    pending_notifications = AdminNotification.query.filter_by(is_read=False).count() if current_user.is_admin else 0
    recent_checklists = (DailyChecklist.query if current_user.is_admin else DailyChecklist.query.filter_by(driver_id=current_user.id)).order_by(DailyChecklist.created_at.desc()).limit(5).all()
    return render_template('dashboard.html', expenses=expenses[:8], total=total, fuel=fuel, maint=maint, alerts=alerts, vehicles=vehicles, today_checklist_count=today_checklist_count, pending_notifications=pending_notifications, recent_checklists=recent_checklists)

@main_bp.route('/fuel/new', methods=['GET','POST'])
@login_required
def fuel_new():
    vehicles = Vehicle.query.order_by(Vehicle.plate).all() if current_user.is_admin else []
    vehicle = selected_vehicle()
    if request.method == 'POST':
        vehicle = selected_vehicle()
        if not vehicle: flash('Nenhuma moto vinculada.', 'danger'); return redirect(request.url)
        try:
            exp = Expense(expense_type='FUEL', expense_date=datetime.strptime(request.form['expense_date'],'%Y-%m-%d').date(), amount=Decimal(request.form['amount'].replace(',','.')), odometer=None, receipt_path='pending', notes=None, created_by_id=current_user.id, vehicle_id=vehicle.id)
            exp.fuel = FuelDetail(liters=Decimal(request.form.get('liters','0').replace(',','.')) if request.form.get('liters') else None, fuel_type=request.form.get('fuel_type'), station=request.form.get('station'))
            db.session.add(exp); db.session.flush()
            exp.receipt_path = save_receipt(request.files.get('receipt'), exp.id)
            add_admin_notification('FUEL', 'Novo abastecimento', f'{current_user.name} registrou abastecimento da moto {vehicle.plate} no valor de R$ {exp.amount}.')
            db.session.commit(); flash('Abastecimento registrado.', 'success'); return redirect(url_for('main.history'))
        except Exception as exc:
            db.session.rollback(); flash(str(exc), 'danger')
    return render_template('driver/fuel_form.html', vehicles=vehicles, vehicle=vehicle, today=date.today().isoformat())

@main_bp.route('/maintenance/new', methods=['GET','POST'])
@login_required
def maintenance_new():
    vehicles = Vehicle.query.order_by(Vehicle.plate).all() if current_user.is_admin else []
    vehicle = selected_vehicle()
    if request.method == 'POST':
        vehicle = selected_vehicle()
        if not vehicle: flash('Nenhuma moto vinculada.', 'danger'); return redirect(request.url)
        try:
            start = datetime.strptime(request.form['start_date'],'%Y-%m-%d').date()
            same = request.form.get('same_day') == 'on'
            end = start if same else datetime.strptime(request.form['end_date'],'%Y-%m-%d').date()
            if end < start: raise ValueError('A data final não pode ser anterior à inicial.')
            km = request.form.get('odometer', type=int)
            exp = Expense(expense_type='MAINTENANCE', expense_date=start, amount=Decimal(request.form['amount'].replace(',','.')), odometer=km, receipt_path='pending', notes=request.form.get('notes'), created_by_id=current_user.id, vehicle_id=vehicle.id)
            exp.maintenance = MaintenanceDetail(start_date=start, same_day=same, end_date=end, description=request.form['description'], workshop=request.form.get('workshop'), status='COMPLETED' if same else request.form.get('status','IN_PROGRESS'))
            if km and km > (vehicle.current_km or 0): vehicle.current_km = km
            vehicle.status = 'AVAILABLE' if same or exp.maintenance.status == 'COMPLETED' else 'MAINTENANCE'
            db.session.add(exp); db.session.flush()
            exp.receipt_path = save_receipt(request.files.get('receipt'), exp.id)
            if request.form.get('is_oil_change') == 'on':
                interval = request.form.get('oil_interval_km', type=int) or 3000
                months = request.form.get('oil_interval_months', type=int) or 6
                db.session.add(OilChange(change_date=start, odometer=km or vehicle.current_km or 0, next_change_km=(km or vehicle.current_km or 0)+interval, next_change_date=start+timedelta(days=months*30), oil_type=request.form.get('oil_type'), vehicle_id=vehicle.id, expense_id=exp.id))
            add_admin_notification('MAINTENANCE', 'Nova manutenção', f'{current_user.name} registrou manutenção da moto {vehicle.plate}: {exp.maintenance.description}.')
            db.session.commit(); flash('Manutenção registrada.', 'success'); return redirect(url_for('main.history'))
        except Exception as exc:
            db.session.rollback(); flash(str(exc), 'danger')
    return render_template('driver/maintenance_form.html', vehicles=vehicles, vehicle=vehicle, today=date.today().isoformat())

@main_bp.route('/history')
@login_required
def history():
    q = Expense.query
    if not current_user.is_admin: q = q.filter_by(created_by_id=current_user.id)
    kind = request.args.get('type')
    if kind: q = q.filter_by(expense_type=kind)
    return render_template('driver/history.html', expenses=q.order_by(Expense.expense_date.desc(), Expense.id.desc()).all())

@main_bp.route('/expense/<int:expense_id>/receipt')
@login_required
def expense_receipt(expense_id):
    exp = db.session.get(Expense, expense_id) or abort(404)
    if not current_user.is_admin and exp.created_by_id != current_user.id:
        return ('', 403)
    stored = StoredFile.query.filter_by(entity_type='EXPENSE', entity_id=exp.id).order_by(StoredFile.id.desc()).first()
    if stored:
        return send_file(BytesIO(stored.content), mimetype=stored.mime_type, download_name=stored.original_name, as_attachment=request.args.get('download') == '1')
    legacy = Path(current_app.config['UPLOAD_FOLDER']) / (exp.receipt_path or '')
    if legacy.is_file():
        return send_from_directory(current_app.config['UPLOAD_FOLDER'], legacy.name, as_attachment=request.args.get('download') == '1')
    return render_template('file_unavailable.html', expense=exp), 404

@main_bp.route('/receipt/<path:name>')
@login_required
def receipt(name):
    exp = Expense.query.filter_by(receipt_path=name).first_or_404()
    return redirect(url_for('main.expense_receipt', expense_id=exp.id, download=request.args.get('download')))

@main_bp.route('/files/<token>')
@login_required
def stored_file(token):
    stored = StoredFile.query.filter_by(token=token).first_or_404()
    if not current_user.is_admin and stored.uploaded_by_id != current_user.id:
        return ('', 403)
    return send_file(BytesIO(stored.content), mimetype=stored.mime_type, download_name=stored.original_name, as_attachment=request.args.get('download') == '1')

@main_bp.route('/checklist/new', methods=['GET','POST'])
@login_required
def checklist_new():
    own_vehicle = current_user.vehicle
    all_vehicles = Vehicle.query.order_by(Vehicle.plate).all()
    if request.method == 'POST':
        try:
            vehicle_id = request.form.get('vehicle_id', type=int)
            vehicle = db.session.get(Vehicle, vehicle_id)
            if not vehicle:
                raise ValueError('Selecione a moto utilizada.')
            borrowed = not own_vehicle or vehicle.id != own_vehicle.id
            reason = request.form.get('borrow_reason','').strip()
            if borrowed and not reason:
                raise ValueError('Informe o motivo do uso da moto de outro motorista.')
            existing = DailyChecklist.query.filter_by(driver_id=current_user.id, vehicle_id=vehicle.id, checklist_date=date.today()).first()
            if existing:
                flash('O checklist desta moto já foi realizado hoje.', 'warning')
                return redirect(url_for('main.checklist_detail', checklist_id=existing.id))
            has_damage = request.form.get('has_damage') == 'yes'
            damage_description = request.form.get('damage_description','').strip()
            if has_damage and not damage_description:
                raise ValueError('Descreva a avaria encontrada.')
            checklist = DailyChecklist(
                checklist_date=date.today(), driver_id=current_user.id, vehicle_id=vehicle.id,
                owner_driver_id=vehicle.driver_id, borrowed_vehicle=borrowed, borrow_reason=reason or None,
                tires_ok=request.form.get('tires_ok') == 'ok', brakes_ok=request.form.get('brakes_ok') == 'ok',
                lights_ok=request.form.get('lights_ok') == 'ok', indicators_ok=request.form.get('indicators_ok') == 'ok',
                mirrors_ok=request.form.get('mirrors_ok') == 'ok', horn_ok=request.form.get('horn_ok') == 'ok',
                chain_ok=request.form.get('chain_ok') == 'ok', general_condition=request.form.get('general_condition','GOOD'),
                has_damage=has_damage, damage_description=damage_description or None,
                status='PENDING_WHATSAPP' if borrowed else ('DAMAGE_REPORTED' if has_damage else 'COMPLETED'),
                share_token=secrets.token_urlsafe(24)
            )
            db.session.add(checklist); db.session.flush()
            required = [('front_photo','CHECKLIST_FRONT'),('rear_photo','CHECKLIST_REAR'),('right_photo','CHECKLIST_RIGHT'),('left_photo','CHECKLIST_LEFT')]
            for field, category in required:
                store_uploaded_file(request.files.get(field), category, 'CHECKLIST', checklist.id, images_only=True)
            if has_damage:
                store_uploaded_file(request.files.get('damage_photo'), 'CHECKLIST_DAMAGE', 'CHECKLIST', checklist.id, images_only=True)
            add_admin_notification('CHECKLIST', 'Novo checklist diário', f'{current_user.name} enviou o checklist da moto {vehicle.plate}.', checklist.id)
            if borrowed:
                add_admin_notification('BORROWED_VEHICLE', 'Moto utilizada por outro motorista', f'{current_user.name} está utilizando a moto {vehicle.plate}. Motivo: {reason}', checklist.id)
            if has_damage:
                add_admin_notification('DAMAGE', 'Avaria informada no checklist', f'{current_user.name} informou avaria na moto {vehicle.plate}: {damage_description}', checklist.id)
            db.session.commit()
            flash('Checklist salvo com sucesso.', 'success')
            return redirect(url_for('main.checklist_detail', checklist_id=checklist.id))
        except Exception as exc:
            db.session.rollback(); flash(str(exc), 'danger')
    return render_template('driver/checklist_form.html', own_vehicle=own_vehicle, vehicles=all_vehicles, today=date.today())

@main_bp.route('/checklists')
@login_required
def checklist_history():
    q = DailyChecklist.query
    if not current_user.is_admin:
        q = q.filter_by(driver_id=current_user.id)
    checklists = q.order_by(DailyChecklist.created_at.desc()).all()
    return render_template('driver/checklist_history.html', checklists=checklists)

@main_bp.route('/checklist/<int:checklist_id>')
@login_required
def checklist_detail(checklist_id):
    checklist = db.session.get(DailyChecklist, checklist_id) or abort(404)
    if not current_user.is_admin and checklist.driver_id != current_user.id:
        return ('',403)
    files = StoredFile.query.filter_by(entity_type='CHECKLIST', entity_id=checklist.id).order_by(StoredFile.id).all()
    recipients = AlertRecipient.query.filter_by(active=True).order_by(AlertRecipient.name).all()
    base_url = os.getenv('ONLINE_URL') or request.url_root.rstrip('/')
    share_url = f"{base_url}{url_for('main.checklist_share', token=checklist.share_token)}"
    message = quote(f"🏍️ *Favela Llog Controle de Veículos*\n\n*Uso temporário de moto*\nMotorista: {checklist.driver.name}\nMoto: {checklist.vehicle.brand} {checklist.vehicle.model}\nPlaca: {checklist.vehicle.plate}\nResponsável original: {checklist.owner_driver.name if checklist.owner_driver else 'Sem vínculo'}\nMotivo: {checklist.borrow_reason or '-'}\nData: {checklist.checklist_date.strftime('%d/%m/%Y')}\n\nChecklist e imagens: {share_url}")
    whatsapp_links=[]
    for recipient in recipients:
        phone=normalize_whatsapp_phone(recipient.phone)
        if phone: whatsapp_links.append({'name':recipient.name,'url':f'https://wa.me/{phone}?text={message}'})
    return render_template('driver/checklist_detail.html', checklist=checklist, files=files, whatsapp_links=whatsapp_links)

@main_bp.route('/checklist/<int:checklist_id>/confirm-whatsapp', methods=['POST'])
@login_required
def checklist_confirm_whatsapp(checklist_id):
    checklist = db.session.get(DailyChecklist, checklist_id) or abort(404)
    if not current_user.is_admin and checklist.driver_id != current_user.id:
        return ('',403)
    checklist.whatsapp_sent_at = datetime.utcnow()
    checklist.whatsapp_confirmed_by_id = current_user.id
    checklist.status = 'DAMAGE_REPORTED' if checklist.has_damage else 'COMPLETED'
    db.session.commit(); flash('Envio pelo WhatsApp confirmado e registrado no histórico.', 'success')
    return redirect(url_for('main.checklist_detail', checklist_id=checklist.id))

@main_bp.route('/checklist/share/<token>')
def checklist_share(token):
    checklist = DailyChecklist.query.filter_by(share_token=token).first_or_404()
    files = StoredFile.query.filter_by(entity_type='CHECKLIST', entity_id=checklist.id).order_by(StoredFile.id).all()
    return render_template('driver/checklist_share.html', checklist=checklist, files=files)

@main_bp.route('/checklist/share/<token>/file/<file_token>')
def checklist_share_file(token, file_token):
    checklist = DailyChecklist.query.filter_by(share_token=token).first_or_404()
    stored = StoredFile.query.filter_by(token=file_token, entity_type='CHECKLIST', entity_id=checklist.id).first_or_404()
    return send_file(BytesIO(stored.content), mimetype=stored.mime_type, download_name=stored.original_name, as_attachment=request.args.get('download') == '1')

@main_bp.route('/admin/checklists')
@login_required
@admin_required
def admin_checklists():
    checklists = DailyChecklist.query.order_by(DailyChecklist.created_at.desc()).all()
    notifications = AdminNotification.query.order_by(AdminNotification.created_at.desc()).limit(50).all()
    return render_template('admin/checklists.html', checklists=checklists, notifications=notifications)

@main_bp.route('/admin/users', methods=['GET','POST'])
@login_required
@admin_required
def users():
    if request.method == 'POST':
        try:
            if request.form['password'] != request.form['confirm_password']: raise ValueError('As senhas não conferem.')
            u = User(name=request.form['name'], username=request.form['username'].strip(), email=request.form.get('email'), phone=request.form.get('phone'), role=request.form['role'], must_change_password=True)
            u.set_password(request.form['password']); db.session.add(u); db.session.commit(); flash('Usuário criado.', 'success')
        except Exception as exc: db.session.rollback(); flash(str(exc), 'danger')
    return render_template('admin/users.html', users=User.query.order_by(User.active.desc(), User.name).all())

@main_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash('Você não pode excluir o próprio usuário administrador.', 'danger')
        return redirect(url_for('main.users'))
    if user.role != 'DRIVER':
        flash('A exclusão por esta opção é permitida somente para motoristas.', 'danger')
        return redirect(url_for('main.users'))
    try:
        if user.vehicle:
            user.vehicle.driver_id = None
        # Exclusão segura: bloqueia o acesso e preserva o histórico operacional.
        user.active = False
        user.must_change_password = False
        user.username = f'{user.username}__excluido_{user.id}_{int(datetime.utcnow().timestamp())}'[:80]
        if '(Excluído)' not in user.name:
            user.name = f'{user.name} (Excluído)'
        add_admin_notification('DRIVER_DELETED', 'Motorista excluído', f'O administrador excluiu/desativou o cadastro de {user.name}. O histórico foi preservado.')
        db.session.commit()
        flash('Motorista excluído do acesso. O histórico foi preservado.', 'success')
    except Exception as exc:
        db.session.rollback(); flash(str(exc), 'danger')
    return redirect(url_for('main.users'))

@main_bp.route('/admin/notifications/status')
@login_required
@admin_required
def notifications_status():
    unread = AdminNotification.query.filter_by(is_read=False).order_by(AdminNotification.id.desc()).all()
    latest = unread[0] if unread else None
    return jsonify({
        'count': len(unread),
        'latest_id': latest.id if latest else 0,
        'latest_title': latest.title if latest else '',
        'latest_message': latest.message if latest else '',
        'alerts_url': url_for('main.alerts'),
    })

@main_bp.route('/admin/notifications/read-all', methods=['POST'])
@login_required
@admin_required
def notifications_read_all():
    AdminNotification.query.filter_by(is_read=False).update({'is_read': True})
    db.session.commit()
    flash('Notificações marcadas como lidas.', 'success')
    return redirect(request.referrer or url_for('main.alerts'))

@main_bp.route('/admin/vehicles', methods=['GET','POST'])
@login_required
@admin_required
def vehicles():
    if request.method == 'POST':
        try:
            v = Vehicle(plate=request.form['plate'].upper().replace('-',''), brand=request.form['brand'], model=request.form['model'], year=request.form.get('year', type=int), current_km=request.form.get('current_km', type=int) or 0, driver_id=request.form.get('driver_id', type=int) or None)
            db.session.add(v); db.session.commit(); flash('Veículo cadastrado.', 'success')
        except Exception as exc: db.session.rollback(); flash(str(exc), 'danger')
    drivers = User.query.filter_by(role='DRIVER', active=True).order_by(User.name).all()
    return render_template('admin/vehicles.html', vehicles=Vehicle.query.order_by(Vehicle.plate).all(), drivers=drivers)

def normalize_whatsapp_phone(value):
    digits = ''.join(ch for ch in (value or '') if ch.isdigit())
    if len(digits) in (10, 11):
        digits = '55' + digits
    return digits

def whatsapp_message(alert):
    vehicle = alert['vehicle']
    driver = vehicle.driver.name if vehicle.driver else 'Não vinculado'
    return (
        "🚨 *Favela Llog Controle de Veículos*\n\n"
        f"*{alert['title']}*\n"
        f"Moto: {vehicle.brand} {vehicle.model}\n"
        f"Placa: {vehicle.plate}\n"
        f"Motorista: {driver}\n"
        f"{alert['detail']}\n\n"
        "Acesse o sistema para registrar ou acompanhar a manutenção."
    )

def attach_whatsapp_links(alerts, recipients):
    for alert in alerts:
        alert['whatsapp_links'] = []
        message = quote(whatsapp_message(alert))
        for recipient in recipients:
            phone = normalize_whatsapp_phone(recipient.phone)
            if phone:
                alert['whatsapp_links'].append({
                    'name': recipient.name,
                    'url': f'https://wa.me/{phone}?text={message}'
                })
    return alerts

@main_bp.route('/admin/alerts', methods=['GET','POST'])
@login_required
@admin_required
def alerts():
    if request.method == 'POST':
        try:
            phone = normalize_whatsapp_phone(request.form.get('phone'))
            if len(phone) < 12:
                raise ValueError('Informe um WhatsApp válido com DDD.')
            recipient = AlertRecipient(
                name=request.form['name'].strip(),
                phone=phone,
                # Mantém compatibilidade com bancos antigos que exigiam e-mail.
                email=f'{phone}@whatsapp.local'
            )
            db.session.add(recipient)
            db.session.commit()
            flash('Contato de WhatsApp adicionado.', 'success')
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    recipients = AlertRecipient.query.filter_by(active=True).order_by(AlertRecipient.name).all()
    active_alerts = attach_whatsapp_links(build_oil_alerts(), recipients)
    system_notifications = AdminNotification.query.order_by(AdminNotification.created_at.desc()).limit(100).all()
    return render_template('admin/alerts.html', alerts=active_alerts, recipients=recipients, system_notifications=system_notifications)

def build_oil_alerts(vehicle_id=None):
    q = Vehicle.query
    if vehicle_id: q = q.filter_by(id=vehicle_id)
    result=[]
    for v in q.all():
        last = OilChange.query.filter_by(vehicle_id=v.id).order_by(OilChange.change_date.desc()).first()
        if not last:
            result.append({'level':'warning','vehicle':v,'title':'Sem registro de troca de óleo','detail':'Cadastre a primeira troca.'}); continue
        remaining = last.next_change_km - (v.current_km or 0)
        overdue_date = last.next_change_date and date.today() > last.next_change_date
        if remaining <= 0 or overdue_date: level='danger'; title='Troca de óleo vencida'
        elif remaining <= 500: level='warning'; title='Troca de óleo próxima'
        else: continue
        result.append({'level':level,'vehicle':v,'title':title,'detail':f"Atual {v.current_km or 0} km · Próxima {last.next_change_km} km · Restam {remaining} km"})
    return result

