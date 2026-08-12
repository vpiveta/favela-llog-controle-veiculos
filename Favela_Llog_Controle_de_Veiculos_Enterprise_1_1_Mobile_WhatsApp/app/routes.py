from datetime import datetime
from decimal import Decimal
from functools import wraps
from pathlib import Path
from io import BytesIO
import os, uuid, secrets
from urllib.parse import quote
from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, send_file, url_for, abort, jsonify
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename
from .models import db, User, Vehicle, Expense, FuelDetail, MaintenanceDetail, OilChange, AlertRecipient, StoredFile, DailyChecklist, AdminNotification, OilAlertStatus, AuditLog
from .storage import is_configured as storage_is_configured, upload_bytes, download_bytes, SupabaseStorageError
from .time_utils import local_today, utc_now

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
    safe_name = secure_filename(file.filename) or f'{category}.{ext}'
    mime_type = file.mimetype or ('image/jpeg' if images_only else 'application/octet-stream')
    storage_bucket = None
    storage_path = None
    db_content = data
    if storage_is_configured():
        storage_path = f"{entity_type.lower()}/{entity_id}/{category.lower()}/{token}-{safe_name}"
        result = upload_bytes(storage_path, data, mime_type)
        storage_bucket = result.bucket
        storage_path = result.path
        # Mantém o banco leve. O campo continua com bytes vazios por compatibilidade com bancos existentes.
        db_content = b''
    stored = StoredFile(
        token=token, original_name=safe_name, mime_type=mime_type,
        file_size=len(data), category=category, entity_type=entity_type, entity_id=entity_id,
        uploaded_by_id=current_user.id, content=db_content,
        storage_bucket=storage_bucket, storage_path=storage_path,
        storage_migrated_at=utc_now() if storage_path else None,
    )
    db.session.add(stored)
    return token

def save_receipt(file, expense):
    """Armazena comprovantes de carros e motos em categorias independentes."""
    if expense.asset_type == 'CAR':
        return store_uploaded_file(file, 'CAR_FUEL_RECEIPT', 'CAR_EXPENSE', expense.id, images_only=False)
    return store_uploaded_file(file, 'MOTORCYCLE_RECEIPT', 'MOTORCYCLE_EXPENSE', expense.id, images_only=False)


def save_car_plate_photo(file, expense):
    return store_uploaded_file(file, 'CAR_PLATE_PHOTO', 'CAR_EXPENSE', expense.id, images_only=True)


def car_plate_photo_ids(expenses):
    ids = [expense.id for expense in expenses if expense.asset_type == 'CAR']
    if not ids:
        return set()
    rows = db.session.query(StoredFile.entity_id).filter(
        StoredFile.entity_type == 'CAR_EXPENSE',
        StoredFile.category == 'CAR_PLATE_PHOTO',
        StoredFile.entity_id.in_(ids),
    ).all()
    return {row[0] for row in rows}


def parse_money(field, label='valor'):
    raw = (request.form.get(field) or '').strip()
    if ',' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    try:
        value = Decimal(raw)
    except Exception as exc:
        raise ValueError(f'Informe um {label} válido.') from exc
    if not value.is_finite() or value <= 0:
        raise ValueError(f'O {label} deve ser maior que zero.')
    try:
        return value.quantize(Decimal('0.01'))
    except Exception as exc:
        raise ValueError(f'Informe um {label} válido.') from exc

def active_checklist_for_driver(user):
    """Última retirada ainda não encerrada por um checklist de devolução."""
    latest = DailyChecklist.query.filter_by(
        driver_id=user.id, is_deleted=False
    ).order_by(
        DailyChecklist.created_at.desc(), DailyChecklist.id.desc()
    ).first()
    if not latest or latest.checklist_type != 'RETIRADA':
        return None
    return latest


def selected_vehicle(prefer_active_checklist=False):
    if current_user.is_admin:
        vehicle_id = (
            request.form.get('motorcycle_vehicle_id', type=int)
            or request.form.get('vehicle_id', type=int)
            or request.args.get('vehicle_id', type=int)
        )
        vehicle = db.session.get(Vehicle, vehicle_id) if vehicle_id else None
        return vehicle if vehicle and vehicle.vehicle_type == 'MOTORCYCLE' else None
    if prefer_active_checklist:
        active_checklist = active_checklist_for_driver(current_user)
        if active_checklist:
            return active_checklist.vehicle
    vehicle = current_user.vehicle
    return vehicle if vehicle and vehicle.vehicle_type == 'MOTORCYCLE' else None

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
    today = local_today()
    month_start = today.replace(day=1)
    q = Expense.query.filter(Expense.expense_date >= month_start, Expense.is_deleted.is_(False))
    if not current_user.is_admin:
        q = q.filter(Expense.created_by_id == current_user.id)
    expenses = q.order_by(Expense.expense_date.desc()).all()
    total = sum((Decimal(e.amount) for e in expenses), Decimal('0'))
    motorcycle_total = sum((Decimal(e.amount) for e in expenses if e.asset_type == 'MOTORCYCLE'), Decimal('0'))
    car_total = sum((Decimal(e.amount) for e in expenses if e.asset_type == 'CAR'), Decimal('0'))
    motorcycle_fuel = sum((Decimal(e.amount) for e in expenses if e.expense_type == 'FUEL' and e.asset_type == 'MOTORCYCLE'), Decimal('0'))
    car_fuel = sum((Decimal(e.amount) for e in expenses if e.expense_type == 'FUEL' and e.asset_type == 'CAR'), Decimal('0'))
    maintenance_total = sum((Decimal(e.amount) for e in expenses if e.expense_type == 'MAINTENANCE'), Decimal('0'))
    # O valor do óleo é explícito. A nota inteira de manutenção nunca é mais
    # tratada automaticamente como troca de óleo.
    oil = Decimal('0')
    for expense in expenses:
        detail = expense.maintenance
        if expense.expense_type != 'MAINTENANCE' or not detail or not detail.is_oil_change or detail.oil_amount is None:
            continue
        explicit_oil = max(Decimal('0'), Decimal(detail.oil_amount))
        oil += min(explicit_oil, Decimal(expense.amount))
    maintenance_other = maintenance_total - oil
    vehicle_scope = (
        current_user.vehicle.id
        if not current_user.is_admin and current_user.vehicle and current_user.vehicle.vehicle_type == 'MOTORCYCLE'
        else None
    )
    oil_statuses = build_oil_statuses(vehicle_scope) if current_user.is_admin or vehicle_scope else []
    alerts = build_oil_alerts(vehicle_scope) if current_user.is_admin or vehicle_scope else []
    if current_user.is_admin:
        motorcycles = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE').order_by(Vehicle.plate).all()
        cars = Vehicle.query.filter_by(vehicle_type='CAR').order_by(Vehicle.plate).all()
    else:
        motorcycles = [current_user.vehicle] if current_user.vehicle and current_user.vehicle.vehicle_type == 'MOTORCYCLE' else []
        cars = []
    maintenance_scope = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE', status='MAINTENANCE')
    if not current_user.is_admin:
        maintenance_scope = maintenance_scope.filter_by(driver_id=current_user.id)
    maintenance_vehicles = []
    for maintenance_vehicle in maintenance_scope.order_by(Vehicle.plate).all():
        open_expense = Expense.query.join(MaintenanceDetail).filter(
            Expense.vehicle_id == maintenance_vehicle.id,
            Expense.is_deleted.is_(False),
            MaintenanceDetail.status == 'IN_PROGRESS',
        ).order_by(Expense.expense_date.desc(), Expense.id.desc()).first()
        maintenance_vehicles.append({'vehicle': maintenance_vehicle, 'expense': open_expense})
    today_checklists = DailyChecklist.query.filter_by(checklist_date=today, is_deleted=False)
    if not current_user.is_admin:
        today_checklists = today_checklists.filter_by(driver_id=current_user.id)
    today_checklist_count = today_checklists.count()
    pending_notifications = AdminNotification.query.filter_by(is_read=False).count() if current_user.is_admin else 0
    recent_q = DailyChecklist.query.filter_by(is_deleted=False)
    if not current_user.is_admin: recent_q = recent_q.filter_by(driver_id=current_user.id)
    recent_checklists = recent_q.order_by(DailyChecklist.created_at.desc()).limit(5).all()
    driver_costs=[]
    if current_user.is_admin:
        totals={}
        for e in expenses:
            totals[e.created_by.name]=totals.get(e.created_by.name, Decimal('0'))+Decimal(e.amount)
        driver_costs=sorted(totals.items(), key=lambda x:x[1], reverse=True)[:10]
    return render_template('dashboard.html', expenses=expenses[:8], total=total,
        motorcycle_total=motorcycle_total, car_total=car_total,
        motorcycle_fuel=motorcycle_fuel, car_fuel=car_fuel,
        maint=maintenance_other, oil=oil, alerts=alerts, oil_statuses=oil_statuses,
        motorcycles=motorcycles, cars=cars, maintenance_vehicles=maintenance_vehicles,
        car_plate_photo_ids=car_plate_photo_ids(expenses[:8]),
        today=today, today_checklist_count=today_checklist_count, pending_notifications=pending_notifications,
        recent_checklists=recent_checklists, driver_costs=driver_costs)

@main_bp.route('/fuel/new', methods=['GET','POST'])
@login_required
def fuel_new():
    motorcycles = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE').order_by(Vehicle.plate).all() if current_user.is_admin else []
    cars = Vehicle.query.filter_by(vehicle_type='CAR').order_by(Vehicle.plate).all()
    admins = User.query.filter_by(role='ADMIN', active=True).order_by(User.name).all()
    active_checklist = None if current_user.is_admin else active_checklist_for_driver(current_user)
    motorcycle_vehicle = selected_vehicle(prefer_active_checklist=True)
    selected_type = ((request.form.get('vehicle_type') if request.method == 'POST' else request.args.get('type')) or 'MOTORCYCLE').upper()
    if selected_type not in {'MOTORCYCLE', 'CAR'}:
        selected_type = 'MOTORCYCLE'
    if request.method == 'POST':
        active_checklist = None if current_user.is_admin else active_checklist_for_driver(current_user)
        try:
            authorized_by = None
            if selected_type == 'CAR':
                vehicle = db.session.get(Vehicle, request.form.get('car_vehicle_id', type=int))
                if not vehicle or vehicle.vehicle_type != 'CAR':
                    raise ValueError('Selecione o carro abastecido.')
                authorized_by = db.session.get(User, request.form.get('authorized_by_id', type=int))
                if not authorized_by or not authorized_by.active or not authorized_by.is_admin:
                    raise ValueError('Selecione o ADM que autorizou o abastecimento do carro.')
                plate_photo = request.files.get('plate_photo')
                if not plate_photo or not plate_photo.filename:
                    raise ValueError('A foto da placa do carro é obrigatória.')
            else:
                vehicle = selected_vehicle(prefer_active_checklist=True)
                if not vehicle:
                    raise ValueError('Nenhuma moto vinculada.')
            odometer = request.form.get('odometer', type=int)
            if odometer is None or odometer < 0:
                raise ValueError(f"Informe a quilometragem atual d{'o carro' if selected_type == 'CAR' else 'a moto'}.")
            amount = parse_money('amount', 'valor do abastecimento')
            liters = parse_money('liters', 'volume em litros') if request.form.get('liters','').strip() else None
            exp = Expense(
                expense_type='FUEL',
                expense_date=datetime.strptime(request.form['expense_date'],'%Y-%m-%d').date(),
                amount=amount, asset_type=selected_type,
                odometer=odometer,
                receipt_path='pending', notes=None,
                created_by_id=current_user.id, authorized_by_id=authorized_by.id if authorized_by else None,
                vehicle_id=vehicle.id,
            )
            exp.fuel = FuelDetail(
                liters=liters,
                fuel_type='GASOLINE',
                station=request.form.get('station','').strip() or None,
            )
            if odometer > (vehicle.current_km or 0):
                vehicle.current_km = odometer
            db.session.add(exp); db.session.flush()
            exp.receipt_path = save_receipt(request.files.get('receipt'), exp)
            if selected_type == 'CAR':
                save_car_plate_photo(plate_photo, exp)
            asset_label = 'carro' if selected_type == 'CAR' else 'moto'
            authorization = f' Autorizado por {authorized_by.name}.' if authorized_by else ''
            add_admin_notification(
                'CAR_FUEL' if selected_type == 'CAR' else 'FUEL',
                f'Novo abastecimento de {asset_label}',
                f'{current_user.name} registrou abastecimento do {asset_label} {vehicle.plate}, com {odometer} km, no valor de R$ {exp.amount}.{authorization}',
            )
            db.session.commit()
            flash(f'Abastecimento do {asset_label} registrado.', 'success')
            return redirect(url_for('main.history', asset_type=selected_type))
        except Exception as exc:
            db.session.rollback(); flash(str(exc), 'danger')
    return render_template(
        'driver/fuel_form.html', motorcycles=motorcycles, cars=cars, admins=admins,
        vehicle=motorcycle_vehicle, active_checklist=active_checklist,
        selected_type=selected_type, today=local_today().isoformat(),
    )

@main_bp.route('/maintenance/new', methods=['GET','POST'])
@login_required
def maintenance_new():
    vehicles = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE').order_by(Vehicle.plate).all() if current_user.is_admin else []
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
            if km is None or km < 0:
                raise ValueError('Informe a quilometragem atual da moto.')
            amount = parse_money('amount', 'valor total da manutenção')
            is_oil_change = request.form.get('is_oil_change') == 'on'
            oil_amount = parse_money('oil_amount', 'valor da troca de óleo') if is_oil_change else None
            if oil_amount is not None and oil_amount > amount:
                raise ValueError('O valor da troca de óleo não pode ser maior que o valor total da manutenção.')
            maintenance_status = 'COMPLETED' if same else request.form.get('status','IN_PROGRESS')
            if maintenance_status not in {'IN_PROGRESS', 'COMPLETED'}:
                raise ValueError('Status de manutenção inválido.')
            exp = Expense(
                expense_type='MAINTENANCE', expense_date=start, amount=amount,
                asset_type='MOTORCYCLE', odometer=km, receipt_path='pending',
                notes=request.form.get('notes','').strip() or None,
                created_by_id=current_user.id, vehicle_id=vehicle.id,
            )
            exp.maintenance = MaintenanceDetail(
                start_date=start, same_day=same, end_date=end,
                description=request.form['description'].strip(),
                workshop=request.form.get('workshop','').strip() or None,
                status=maintenance_status, is_oil_change=is_oil_change,
                oil_amount=oil_amount,
            )
            if km and km > (vehicle.current_km or 0): vehicle.current_km = km
            vehicle.status = 'AVAILABLE' if same or exp.maintenance.status == 'COMPLETED' else 'MAINTENANCE'
            db.session.add(exp); db.session.flush()
            exp.receipt_path = save_receipt(request.files.get('receipt'), exp)
            if is_oil_change:
                # O novo ciclo sempre começa exatamente no KM informado no dia.
                base_km = km
                db.session.add(OilChange(change_date=start, odometer=base_km, next_change_km=base_km+990, next_change_date=None, oil_type=request.form.get('oil_type'), vehicle_id=vehicle.id, expense_id=exp.id))
            linked_driver = vehicle.driver.name if vehicle.driver else 'Sem motorista vinculado'
            add_admin_notification('MAINTENANCE', 'Nova manutenção', f'{current_user.name} registrou manutenção da moto {vehicle.plate} (responsável: {linked_driver}): {exp.maintenance.description}.')
            db.session.commit(); flash('Manutenção registrada.', 'success'); return redirect(url_for('main.history'))
        except Exception as exc:
            db.session.rollback(); flash(str(exc), 'danger')
    return render_template('driver/maintenance_form.html', vehicles=vehicles, vehicle=vehicle, today=local_today().isoformat())


@main_bp.route('/admin/maintenance/<int:expense_id>/complete', methods=['POST'])
@login_required
@admin_required
def complete_maintenance(expense_id):
    expense = db.session.get(Expense, expense_id) or abort(404)
    if expense.is_deleted or not expense.maintenance:
        abort(404)
    try:
        completed_at = datetime.strptime(request.form.get('end_date') or local_today().isoformat(), '%Y-%m-%d').date()
        if completed_at < expense.maintenance.start_date:
            raise ValueError('A data de conclusão não pode ser anterior à entrada da moto.')
        expense.maintenance.end_date = completed_at
        expense.maintenance.status = 'COMPLETED'
        expense.vehicle.status = 'AVAILABLE'
        linked_driver = expense.vehicle.driver.name if expense.vehicle.driver else 'Sem motorista vinculado'
        add_admin_notification(
            'MAINTENANCE_COMPLETED', 'Manutenção concluída',
            f'A manutenção da moto {expense.vehicle.plate} foi concluída. Motorista vinculado: {linked_driver}.',
        )
        db.session.commit()
        flash('Manutenção concluída e moto liberada.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(request.referrer or url_for('main.dashboard'))

@main_bp.route('/history')
@login_required
def history():
    q = Expense.query.filter_by(is_deleted=False)
    if not current_user.is_admin: q = q.filter_by(created_by_id=current_user.id)
    kind = request.args.get('type')
    if kind: q = q.filter_by(expense_type=kind)
    expenses = q.order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    motorcycle_expenses = [expense for expense in expenses if expense.asset_type == 'MOTORCYCLE']
    car_expenses = [expense for expense in expenses if expense.asset_type == 'CAR']
    return render_template(
        'driver/history.html', motorcycle_expenses=motorcycle_expenses,
        car_expenses=car_expenses,
        motorcycle_total=sum((Decimal(e.amount) for e in motorcycle_expenses), Decimal('0')),
        car_total=sum((Decimal(e.amount) for e in car_expenses), Decimal('0')),
        car_plate_photo_ids=car_plate_photo_ids(car_expenses),
        selected_asset_type=request.args.get('asset_type','').upper(),
    )

@main_bp.route('/expense/<int:expense_id>/receipt')
@login_required
def expense_receipt(expense_id):
    exp = db.session.get(Expense, expense_id) or abort(404)
    if not current_user.is_admin and exp.created_by_id != current_user.id:
        return ('', 403)
    stored = StoredFile.query.filter(
        StoredFile.entity_id == exp.id,
        StoredFile.entity_type.in_(('EXPENSE', 'MOTORCYCLE_EXPENSE', 'CAR_EXPENSE')),
        StoredFile.category.in_(('RECEIPT', 'MOTORCYCLE_RECEIPT', 'CAR_FUEL_RECEIPT')),
    ).order_by(StoredFile.id.desc()).first()
    if stored:
        try:
            if stored.is_in_storage:
                data, mime = download_bytes(stored.storage_bucket, stored.storage_path)
            else:
                data, mime = stored.content, stored.mime_type
            if data:
                return send_file(BytesIO(data), mimetype=mime or stored.mime_type, download_name=stored.original_name, as_attachment=request.args.get('download') == '1')
        except SupabaseStorageError as exc:
            current_app.logger.exception('Falha ao abrir comprovante no Storage')
            flash(str(exc), 'danger')
    legacy = Path(current_app.config['UPLOAD_FOLDER']) / (exp.receipt_path or '')
    if legacy.is_file():
        return send_from_directory(current_app.config['UPLOAD_FOLDER'], legacy.name, as_attachment=request.args.get('download') == '1')
    return render_template('file_unavailable.html', expense=exp), 404


@main_bp.route('/expense/<int:expense_id>/plate-photo')
@login_required
def expense_plate_photo(expense_id):
    exp = db.session.get(Expense, expense_id) or abort(404)
    if exp.asset_type != 'CAR':
        abort(404)
    if not current_user.is_admin and exp.created_by_id != current_user.id:
        return ('', 403)
    stored = StoredFile.query.filter_by(
        entity_type='CAR_EXPENSE', entity_id=exp.id, category='CAR_PLATE_PHOTO'
    ).order_by(StoredFile.id.desc()).first_or_404()
    try:
        if stored.is_in_storage:
            data, mime = download_bytes(stored.storage_bucket, stored.storage_path)
        else:
            data, mime = stored.content, stored.mime_type
        if not data:
            abort(404)
        return send_file(
            BytesIO(data), mimetype=mime or stored.mime_type,
            download_name=stored.original_name,
            as_attachment=request.args.get('download') == '1',
        )
    except SupabaseStorageError as exc:
        current_app.logger.exception('Falha ao abrir foto da placa no Storage')
        abort(503, description=str(exc))

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
    try:
        if stored.is_in_storage:
            data, mime = download_bytes(stored.storage_bucket, stored.storage_path)
        else:
            data, mime = stored.content, stored.mime_type
        if not data:
            abort(404)
        return send_file(BytesIO(data), mimetype=mime or stored.mime_type, download_name=stored.original_name, as_attachment=request.args.get('download') == '1')
    except SupabaseStorageError as exc:
        current_app.logger.exception('Falha ao abrir arquivo no Storage')
        abort(503, description=str(exc))

@main_bp.route('/checklist/new', methods=['GET','POST'])
@login_required
def checklist_new():
    own_vehicle = current_user.vehicle if current_user.vehicle and current_user.vehicle.vehicle_type == 'MOTORCYCLE' else None
    all_vehicles = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE').order_by(Vehicle.plate).all()
    requested_type = (request.form.get('checklist_type') if request.method == 'POST' else request.args.get('type')) or 'RETIRADA'
    checklist_type = requested_type.upper()
    if checklist_type not in {'RETIRADA', 'DEVOLUCAO'}:
        checklist_type = 'RETIRADA'
    active_before = active_checklist_for_driver(current_user)
    default_vehicle = active_before.vehicle if checklist_type == 'DEVOLUCAO' and active_before else own_vehicle
    if request.method == 'POST':
        try:
            vehicle_id = request.form.get('vehicle_id', type=int)
            vehicle = db.session.get(Vehicle, vehicle_id)
            if not vehicle or vehicle.vehicle_type != 'MOTORCYCLE':
                raise ValueError('Selecione a moto utilizada.')
            if checklist_type == 'DEVOLUCAO' and active_before and vehicle.id != active_before.vehicle_id:
                raise ValueError(f'A devolução ativa deve ser feita para a moto {active_before.vehicle.plate}.')
            borrowed = not own_vehicle or vehicle.id != own_vehicle.id
            odometer = request.form.get('odometer', type=int)
            if odometer is None or odometer < 0:
                raise ValueError('Informe a quilometragem atual da moto.')
            reason = request.form.get('borrow_reason','').strip()
            if borrowed and checklist_type == 'RETIRADA' and not reason:
                raise ValueError('Informe o motivo do uso da moto de outro motorista.')
            if borrowed and checklist_type == 'DEVOLUCAO' and not reason and active_before and active_before.vehicle_id == vehicle.id:
                reason = active_before.borrow_reason or ''
            existing = DailyChecklist.query.filter_by(
                driver_id=current_user.id, vehicle_id=vehicle.id,
                checklist_date=local_today(), checklist_type=checklist_type,
                is_deleted=False,
            ).first()
            if existing:
                label = 'retirada' if checklist_type == 'RETIRADA' else 'devolução'
                flash(f'O checklist de {label} desta moto já foi realizado hoje.', 'warning')
                return redirect(url_for('main.checklist_detail', checklist_id=existing.id))
            has_damage = request.form.get('has_damage') == 'yes'
            damage_description = request.form.get('damage_description','').strip()
            if has_damage and not damage_description:
                raise ValueError('Descreva a avaria encontrada.')
            checklist = DailyChecklist(
                checklist_date=local_today(), checklist_type=checklist_type,
                driver_id=current_user.id, vehicle_id=vehicle.id, odometer=odometer,
                owner_driver_id=vehicle.driver_id, borrowed_vehicle=borrowed, borrow_reason=reason or None,
                tires_ok=request.form.get('tires_ok') == 'ok', brakes_ok=request.form.get('brakes_ok') == 'ok',
                lights_ok=request.form.get('lights_ok') == 'ok', indicators_ok=request.form.get('indicators_ok') == 'ok',
                mirrors_ok=request.form.get('mirrors_ok') == 'ok', horn_ok=request.form.get('horn_ok') == 'ok',
                chain_ok=request.form.get('chain_ok') == 'ok',
                charger_ok=request.form.get('charger_ok') == 'ok',
                phone_holder_ok=request.form.get('phone_holder_ok') == 'ok',
                top_case_ok=request.form.get('top_case_ok') == 'ok',
                saddlebags_ok=request.form.get('saddlebags_ok') == 'ok',
                general_condition=request.form.get('general_condition','GOOD'),
                has_damage=has_damage, damage_description=damage_description or None,
                status='PENDING_WHATSAPP' if borrowed else ('DAMAGE_REPORTED' if has_damage else 'COMPLETED'),
                share_token=secrets.token_urlsafe(24)
            )
            if odometer > (vehicle.current_km or 0):
                vehicle.current_km = odometer
            db.session.add(checklist); db.session.flush()
            required = [('front_photo','CHECKLIST_FRONT'),('rear_photo','CHECKLIST_REAR'),('right_photo','CHECKLIST_RIGHT'),('left_photo','CHECKLIST_LEFT')]
            for field, category in required:
                store_uploaded_file(request.files.get(field), category, 'CHECKLIST', checklist.id, images_only=True)
            if has_damage:
                store_uploaded_file(request.files.get('damage_photo'), 'CHECKLIST_DAMAGE', 'CHECKLIST', checklist.id, images_only=True)
            action_label = 'retirada' if checklist_type == 'RETIRADA' else 'devolução'
            add_admin_notification('CHECKLIST', f'Novo checklist de {action_label}', f'{current_user.name} enviou o checklist de {action_label} da moto {vehicle.plate}.', checklist.id)
            if borrowed:
                if checklist_type == 'RETIRADA':
                    borrowed_message = f'{current_user.name} está utilizando a moto {vehicle.plate}. Motivo: {reason}'
                    borrowed_title = 'Moto utilizada por outro motorista'
                else:
                    borrowed_message = f'{current_user.name} devolveu a moto {vehicle.plate} após o uso temporário.'
                    borrowed_title = 'Moto de outro motorista devolvida'
                add_admin_notification('BORROWED_VEHICLE', borrowed_title, borrowed_message, checklist.id)
            if has_damage:
                add_admin_notification('DAMAGE', 'Avaria informada no checklist', f'{current_user.name} informou avaria na moto {vehicle.plate}: {damage_description}', checklist.id)
            db.session.commit()
            flash(f'Checklist de {action_label} salvo com sucesso.', 'success')
            return redirect(url_for('main.checklist_detail', checklist_id=checklist.id))
        except Exception as exc:
            db.session.rollback(); flash(str(exc), 'danger')
    return render_template(
        'driver/checklist_form.html', own_vehicle=own_vehicle, vehicles=all_vehicles,
        today=local_today(), checklist_type=checklist_type,
        default_vehicle=default_vehicle, active_checklist=active_before,
    )

@main_bp.route('/checklists')
@login_required
def checklist_history():
    q = DailyChecklist.query.filter_by(is_deleted=False)
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
    recipients = User.query.filter_by(role='DRIVER', active=True).filter(User.phone.isnot(None)).order_by(User.name).all()
    base_url = os.getenv('ONLINE_URL') or request.url_root.rstrip('/')
    share_url = f"{base_url}{url_for('main.checklist_share', token=checklist.share_token)}"
    logo_url = f"{base_url}{url_for('static', filename='img/logo.png')}"
    action_label = 'Devolução' if checklist.checklist_type == 'DEVOLUCAO' else 'Retirada'
    message = quote(f"{logo_url}\n\n🔵⚫ *FAVELA LLOG*\n*Controle de Veículos*\n\n*Checklist de {action_label.lower()}*\nMotorista: {checklist.driver.name}\nMoto: {checklist.vehicle.brand} {checklist.vehicle.model}\nPlaca: {checklist.vehicle.plate}\nResponsável original: {checklist.owner_driver.name if checklist.owner_driver else 'Sem vínculo'}\nMotivo: {checklist.borrow_reason or '-'}\nData: {checklist.checklist_date.strftime('%d/%m/%Y')}\nKM do checklist: {checklist.odometer}\n\nChecklist e imagens: {share_url}")
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
    checklist.whatsapp_sent_at = utc_now()
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
    try:
        if stored.is_in_storage:
            data, mime = download_bytes(stored.storage_bucket, stored.storage_path)
        else:
            data, mime = stored.content, stored.mime_type
        if not data:
            abort(404)
        return send_file(BytesIO(data), mimetype=mime or stored.mime_type, download_name=stored.original_name, as_attachment=request.args.get('download') == '1')
    except SupabaseStorageError as exc:
        current_app.logger.exception('Falha ao abrir arquivo no Storage')
        abort(503, description=str(exc))

@main_bp.route('/admin/checklists')
@login_required
@admin_required
def admin_checklists():
    checklists = DailyChecklist.query.filter_by(is_deleted=False).order_by(DailyChecklist.created_at.desc()).all()
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

@main_bp.route('/admin/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@admin_required
def reset_user_password(user_id):
    user = db.session.get(User, user_id) or abort(404)
    password = request.form.get('new_password','')
    confirmation = request.form.get('confirm_password','')
    if len(password) < 6:
        flash('A nova senha deve ter pelo menos 6 caracteres.', 'danger')
    elif password != confirmation:
        flash('As senhas não conferem.', 'danger')
    else:
        user.set_password(password)
        user.must_change_password = False
        db.session.add(AuditLog(action='RESET_PASSWORD', entity_type='USER', entity_id=user.id,
            description=f'Senha redefinida pelo administrador para {user.name}.', user_id=current_user.id))
        db.session.commit()
        flash(f'Senha de {user.name} redefinida com sucesso.', 'success')
    return redirect(url_for('main.users'))

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
        user.username = f'{user.username}__excluido_{user.id}_{int(utc_now().timestamp())}'[:80]
        if '(Excluído)' not in user.name:
            user.name = f'{user.name} (Excluído)'
        add_admin_notification('DRIVER_DELETED', 'Motorista excluído', f'O administrador excluiu/desativou o cadastro de {user.name}. O histórico foi preservado.')
        db.session.commit()
        flash('Motorista excluído do acesso. O histórico foi preservado.', 'success')
    except Exception as exc:
        db.session.rollback(); flash(str(exc), 'danger')
    return redirect(url_for('main.users'))

@main_bp.route('/admin/expense/<int:expense_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_expense(expense_id):
    exp = db.session.get(Expense, expense_id) or abort(404)
    reason = request.form.get('reason','').strip()
    if request.form.get('confirmation') != 'EXCLUIR' or not reason:
        flash('Informe o motivo e digite EXCLUIR para confirmar.', 'danger')
        return redirect(request.referrer or url_for('main.history'))
    exp.is_deleted=True; exp.deleted_at=utc_now(); exp.deleted_by_id=current_user.id; exp.deletion_reason=reason
    if exp.maintenance and exp.maintenance.status == 'IN_PROGRESS':
        another_open = Expense.query.join(MaintenanceDetail).filter(
            Expense.vehicle_id == exp.vehicle_id,
            Expense.id != exp.id,
            Expense.is_deleted.is_(False),
            MaintenanceDetail.status == 'IN_PROGRESS',
        ).first()
        if not another_open and exp.vehicle.status == 'MAINTENANCE':
            exp.vehicle.status = 'AVAILABLE'
    db.session.add(AuditLog(action='DELETE_EXPENSE', entity_type='EXPENSE', entity_id=exp.id,
        description=f'Lançamento {exp.expense_type} excluído logicamente. Motivo: {reason}', user_id=current_user.id))
    db.session.commit(); flash('Lançamento removido dos painéis. Auditoria preservada.', 'success')
    return redirect(request.referrer or url_for('main.history'))

@main_bp.route('/admin/checklist/<int:checklist_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_checklist(checklist_id):
    checklist=db.session.get(DailyChecklist, checklist_id) or abort(404)
    reason=request.form.get('reason','').strip()
    if request.form.get('confirmation')!='EXCLUIR' or not reason:
        flash('Informe o motivo e digite EXCLUIR para confirmar.', 'danger')
        return redirect(request.referrer or url_for('main.admin_checklists'))
    checklist.is_deleted=True; checklist.deleted_at=utc_now(); checklist.deleted_by_id=current_user.id; checklist.deletion_reason=reason
    db.session.add(AuditLog(action='DELETE_CHECKLIST', entity_type='CHECKLIST', entity_id=checklist.id,
        description=f'Checklist excluído logicamente. Motivo: {reason}', user_id=current_user.id))
    db.session.commit(); flash('Checklist removido do histórico operacional. Auditoria preservada.', 'success')
    return redirect(url_for('main.admin_checklists'))

@main_bp.route('/vehicle/<int:vehicle_id>/borrow-summary')
@login_required
def borrow_vehicle_summary(vehicle_id):
    vehicle=db.session.get(Vehicle, vehicle_id) or abort(404)
    if vehicle.vehicle_type != 'MOTORCYCLE':
        abort(404)
    if current_user.is_admin or (current_user.vehicle and current_user.vehicle.id==vehicle.id):
        return jsonify({'borrowed':False})
    last_checklist=DailyChecklist.query.filter_by(vehicle_id=vehicle.id,is_deleted=False).order_by(DailyChecklist.created_at.desc()).first()
    last_fuel=Expense.query.filter_by(vehicle_id=vehicle.id,expense_type='FUEL',is_deleted=False).order_by(Expense.expense_date.desc(),Expense.id.desc()).first()
    return jsonify({
        'borrowed':True, 'plate':vehicle.plate, 'vehicle':(vehicle.driver.name if vehicle.driver else 'Sem motorista vinculado'),
        'last_checklist': ({'date':last_checklist.checklist_date.strftime('%d/%m/%Y'),'condition':last_checklist.general_condition,'damage':last_checklist.has_damage} if last_checklist else None),
        'last_fuel': ({'date':last_fuel.expense_date.strftime('%d/%m/%Y'),'amount':str(last_fuel.amount)} if last_fuel else None)
    })

@main_bp.route('/admin/notifications/status')
@login_required
@admin_required
def notifications_status():
    unread = AdminNotification.query.filter_by(is_read=False).order_by(AdminNotification.id.desc()).all()
    oil_alerts = [a for a in build_oil_alerts() if not a.get('message_sent')]
    latest = unread[0] if unread else None
    oil_signature = ','.join(f"{a['vehicle'].id}-{a['oil_change'].id}-{a['level']}" for a in oil_alerts)
    latest_oil = oil_alerts[0] if oil_alerts else None
    return jsonify({
        'count': len(unread) + len(oil_alerts),
        'latest_id': f"{latest.id if latest else 0}:{oil_signature}",
        'latest_title': latest.title if latest else (latest_oil['title'] if latest_oil else ''),
        'latest_message': latest.message if latest else (f"{latest_oil['vehicle'].plate} · {latest_oil['detail']}" if latest_oil else ''),
        'alerts_url': url_for('main.alerts'),
    })

@main_bp.route('/admin/notifications/<int:notification_id>/whatsapp-sent', methods=['POST'])
@login_required
@admin_required
def notification_whatsapp_sent(notification_id):
    notification=db.session.get(AdminNotification,notification_id) or abort(404)
    notification.whatsapp_sent_at=utc_now(); notification.whatsapp_sent_by_id=current_user.id; notification.is_read=True
    db.session.commit(); flash('Mensagem marcada como enviada e alerta retirado dos não lidos.', 'success')
    return redirect(url_for('main.alerts'))

@main_bp.route('/admin/oil-alert/sent', methods=['POST'])
@login_required
@admin_required
def oil_alert_sent():
    vehicle_id=request.form.get('vehicle_id',type=int); oil_change_id=request.form.get('oil_change_id',type=int); level=request.form.get('level','')
    status=OilAlertStatus.query.filter_by(vehicle_id=vehicle_id,oil_change_id=oil_change_id,level=level).first()
    if not status:
        status=OilAlertStatus(vehicle_id=vehicle_id,oil_change_id=oil_change_id,level=level)
        db.session.add(status)
    status.message_sent_at=utc_now(); status.message_sent_by_id=current_user.id; status.is_read=True
    db.session.commit(); flash('Mensagem enviada. O alerta saiu dos não lidos e ficou no histórico.', 'success')
    return redirect(url_for('main.alerts'))

@main_bp.route('/admin/notifications/read-all', methods=['POST'])
@login_required
@admin_required
def notifications_read_all():
    AdminNotification.query.filter_by(is_read=False).update({'is_read': True})
    db.session.commit()
    flash('Notificações marcadas como lidas.', 'success')
    return redirect(request.referrer or url_for('main.alerts'))

def assign_vehicle_driver(vehicle, driver_id):
    if vehicle.vehicle_type != 'MOTORCYCLE':
        vehicle.driver_id = None
        return
    if driver_id:
        other = Vehicle.query.filter(Vehicle.driver_id == driver_id, Vehicle.id != vehicle.id).first()
        if other:
            other.driver_id = None
    vehicle.driver_id = driver_id or None

@main_bp.route('/admin/vehicles', methods=['GET','POST'])
@login_required
@admin_required
def vehicles():
    if request.method == 'POST':
        try:
            vehicle_type = request.form.get('vehicle_type','MOTORCYCLE').upper()
            if vehicle_type not in {'MOTORCYCLE', 'CAR'}:
                raise ValueError('Tipo de veículo inválido.')
            status = request.form.get('status','AVAILABLE').upper()
            if status not in {'AVAILABLE', 'MAINTENANCE', 'BLOCKED'}:
                raise ValueError('Status de veículo inválido.')
            if vehicle_type == 'CAR' and status == 'MAINTENANCE':
                status = 'AVAILABLE'
            v = Vehicle(
                plate=request.form['plate'].upper().replace('-','').strip(),
                brand=request.form['brand'].strip(), model=request.form['model'].strip(),
                year=request.form.get('year', type=int), current_km=request.form.get('current_km', type=int) or 0,
                vehicle_type=vehicle_type, status=status,
            )
            db.session.add(v); db.session.flush()
            assign_vehicle_driver(v, request.form.get('driver_id', type=int))
            db.session.commit(); flash(f"{'Moto' if vehicle_type == 'MOTORCYCLE' else 'Carro'} cadastrado.", 'success')
        except Exception as exc: db.session.rollback(); flash(str(exc), 'danger')
    drivers = User.query.filter_by(role='DRIVER', active=True).order_by(User.name).all()
    return render_template('admin/vehicles.html', vehicles=Vehicle.query.order_by(Vehicle.plate).all(), drivers=drivers)

@main_bp.route('/admin/vehicles/<int:vehicle_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_vehicle(vehicle_id):
    vehicle = db.session.get(Vehicle, vehicle_id) or abort(404)
    try:
        plate = request.form['plate'].upper().replace('-','').strip()
        duplicate = Vehicle.query.filter(Vehicle.plate == plate, Vehicle.id != vehicle.id).first()
        if duplicate:
            raise ValueError('Já existe outro veículo com esta placa.')
        vehicle.plate = plate
        vehicle.brand = request.form['brand'].strip()
        vehicle.model = request.form['model'].strip()
        vehicle.year = request.form.get('year', type=int)
        vehicle.current_km = request.form.get('current_km', type=int) or 0
        vehicle_type = request.form.get('vehicle_type','MOTORCYCLE').upper()
        if vehicle_type not in {'MOTORCYCLE', 'CAR'}:
            raise ValueError('Tipo de veículo inválido.')
        vehicle.vehicle_type = vehicle_type
        status = request.form.get('status') or 'AVAILABLE'
        if status not in {'AVAILABLE', 'MAINTENANCE', 'BLOCKED'}:
            raise ValueError('Status de veículo inválido.')
        vehicle.status = 'AVAILABLE' if vehicle_type == 'CAR' and status == 'MAINTENANCE' else status
        assign_vehicle_driver(vehicle, request.form.get('driver_id', type=int))
        db.session.commit(); flash('Veículo atualizado com sucesso.', 'success')
    except Exception as exc:
        db.session.rollback(); flash(str(exc), 'danger')
    return redirect(url_for('main.vehicles'))

def normalize_whatsapp_phone(value):
    digits = ''.join(ch for ch in (value or '') if ch.isdigit())
    if len(digits) in (10, 11):
        digits = '55' + digits
    return digits

def whatsapp_message(alert):
    vehicle = alert['vehicle']
    driver = vehicle.driver.name if vehicle.driver else 'Não vinculado'
    base_url = os.getenv('ONLINE_URL') or request.url_root.rstrip('/')
    logo_url = f"{base_url}{url_for('static', filename='img/logo.png')}"
    return (
        f"{logo_url}\n\n"
        "🔵⚫ *FAVELA LLOG*\n"
        "*Controle de Veículos*\n\n"
        f"🚨 *{alert['title']}*\n"
        f"Moto: {vehicle.brand} {vehicle.model}\n"
        f"Placa: {vehicle.plate}\n"
        f"Motorista: {driver}\n"
        f"KM da última troca: {alert['base_km']} km\n"
        f"KM atual: {alert['current_km']} km\n"
        f"Rodados desde a troca: {alert['traveled_km']} km\n"
        f"Restam: {max(alert['remaining_km'], 0)} km\n\n"
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

@main_bp.route('/admin/alerts')
@login_required
@admin_required
def alerts():
    # Contatos derivados dos motoristas ativos cadastrados no sistema.
    recipients = User.query.filter_by(role='DRIVER', active=True).filter(User.phone.isnot(None)).order_by(User.name).all()
    active_alerts = attach_whatsapp_links(build_oil_alerts(), recipients)
    system_notifications = AdminNotification.query.order_by(AdminNotification.created_at.desc()).limit(100).all()
    oil_history = OilAlertStatus.query.filter(OilAlertStatus.message_sent_at.isnot(None)).order_by(OilAlertStatus.message_sent_at.desc()).limit(50).all()
    return render_template('admin/alerts.html', alerts=active_alerts, recipients=recipients, system_notifications=system_notifications, oil_history=oil_history)

def build_oil_statuses(vehicle_id=None):
    """Calcula o ciclo pelo hodômetro lançado nos checklists desde a última troca."""
    q = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE')
    if vehicle_id:
        q = q.filter_by(id=vehicle_id)
    result = []
    for vehicle in q.order_by(Vehicle.plate).all():
        last_change = OilChange.query.outerjoin(Expense, OilChange.expense_id == Expense.id).filter(
            OilChange.vehicle_id == vehicle.id,
            (OilChange.expense_id.is_(None)) | (Expense.is_deleted.is_(False)),
        ).order_by(
            OilChange.change_date.desc(), OilChange.id.desc()
        ).first()
        if not last_change:
            result.append({
                'vehicle': vehicle, 'oil_change': None, 'base_km': None,
                'current_km': vehicle.current_km or 0, 'traveled_km': 0,
                'remaining_km': 990, 'target_km': None, 'level': 'neutral',
                'status_label': 'Sem troca registrada',
            })
            continue

        latest_checklist_km = db.session.query(db.func.max(DailyChecklist.odometer)).filter(
            DailyChecklist.vehicle_id == vehicle.id,
            DailyChecklist.is_deleted.is_(False),
            DailyChecklist.checklist_date >= last_change.change_date,
        ).scalar()

        # O ciclo avança apenas pelo hodômetro dos checklists diários. Valores de
        # abastecimento ou edição cadastral não alteram silenciosamente o alerta.
        current_km = latest_checklist_km if latest_checklist_km is not None else last_change.odometer
        current_km = max(current_km or 0, last_change.odometer)
        traveled = max(0, current_km - last_change.odometer)
        remaining = 990 - traveled
        target = last_change.odometer + 990
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
            'base_km': last_change.odometer, 'current_km': current_km,
            'traveled_km': traveled, 'remaining_km': remaining,
            'target_km': target, 'level': level, 'status_label': label,
        })
    return result

def build_oil_alerts(vehicle_id=None):
    result = []
    for status_info in build_oil_statuses(vehicle_id):
        last = status_info['oil_change']
        if not last or status_info['remaining_km'] > 200:
            continue
        remaining = status_info['remaining_km']
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
