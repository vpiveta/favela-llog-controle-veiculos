from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import wraps
from pathlib import Path
import os, uuid, smtplib
from email.message import EmailMessage
from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename
from .models import db, User, Vehicle, Expense, FuelDetail, MaintenanceDetail, OilChange, AlertRecipient

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

def save_receipt(file):
    if not file or not file.filename:
        raise ValueError('A foto da nota é obrigatória.')
    ext = file.filename.rsplit('.',1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED:
        raise ValueError('Formato inválido. Use JPG, PNG, WEBP ou PDF.')
    name = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    file.save(Path(current_app.config['UPLOAD_FOLDER']) / name)
    return name

def selected_vehicle():
    if current_user.is_admin:
        vehicle_id = request.form.get('vehicle_id', type=int) or request.args.get('vehicle_id', type=int)
        return db.session.get(Vehicle, vehicle_id) if vehicle_id else None
    return current_user.vehicle

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
    return render_template('dashboard.html', expenses=expenses[:8], total=total, fuel=fuel, maint=maint, alerts=alerts, vehicles=vehicles)

@main_bp.route('/fuel/new', methods=['GET','POST'])
@login_required
def fuel_new():
    vehicles = Vehicle.query.order_by(Vehicle.plate).all() if current_user.is_admin else []
    vehicle = selected_vehicle()
    if request.method == 'POST':
        vehicle = selected_vehicle()
        if not vehicle: flash('Nenhuma moto vinculada.', 'danger'); return redirect(request.url)
        try:
            receipt = save_receipt(request.files.get('receipt'))
            km = request.form.get('odometer', type=int)
            exp = Expense(expense_type='FUEL', expense_date=datetime.strptime(request.form['expense_date'],'%Y-%m-%d').date(), amount=Decimal(request.form['amount'].replace(',','.')), odometer=km, receipt_path=receipt, notes=request.form.get('notes'), created_by_id=current_user.id, vehicle_id=vehicle.id)
            exp.fuel = FuelDetail(liters=Decimal(request.form.get('liters','0').replace(',','.')) if request.form.get('liters') else None, fuel_type=request.form.get('fuel_type'), station=request.form.get('station'))
            if km and km > (vehicle.current_km or 0): vehicle.current_km = km
            db.session.add(exp); db.session.commit(); flash('Abastecimento registrado.', 'success'); return redirect(url_for('main.history'))
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
            receipt = save_receipt(request.files.get('receipt'))
            start = datetime.strptime(request.form['start_date'],'%Y-%m-%d').date()
            same = request.form.get('same_day') == 'on'
            end = start if same else datetime.strptime(request.form['end_date'],'%Y-%m-%d').date()
            if end < start: raise ValueError('A data final não pode ser anterior à inicial.')
            km = request.form.get('odometer', type=int)
            exp = Expense(expense_type='MAINTENANCE', expense_date=start, amount=Decimal(request.form['amount'].replace(',','.')), odometer=km, receipt_path=receipt, notes=request.form.get('notes'), created_by_id=current_user.id, vehicle_id=vehicle.id)
            exp.maintenance = MaintenanceDetail(start_date=start, same_day=same, end_date=end, description=request.form['description'], workshop=request.form.get('workshop'), status='COMPLETED' if same else request.form.get('status','IN_PROGRESS'))
            if km and km > (vehicle.current_km or 0): vehicle.current_km = km
            vehicle.status = 'AVAILABLE' if same or exp.maintenance.status == 'COMPLETED' else 'MAINTENANCE'
            db.session.add(exp); db.session.flush()
            if request.form.get('is_oil_change') == 'on':
                interval = request.form.get('oil_interval_km', type=int) or 3000
                months = request.form.get('oil_interval_months', type=int) or 6
                db.session.add(OilChange(change_date=start, odometer=km or vehicle.current_km or 0, next_change_km=(km or vehicle.current_km or 0)+interval, next_change_date=start+timedelta(days=months*30), oil_type=request.form.get('oil_type'), vehicle_id=vehicle.id, expense_id=exp.id))
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

@main_bp.route('/receipt/<path:name>')
@login_required
def receipt(name):
    exp = Expense.query.filter_by(receipt_path=name).first_or_404()
    if not current_user.is_admin and exp.created_by_id != current_user.id: return ('',403)
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], name)

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
    return render_template('admin/users.html', users=User.query.order_by(User.name).all())

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

@main_bp.route('/admin/alerts', methods=['GET','POST'])
@login_required
@admin_required
def alerts():
    if request.method == 'POST':
        db.session.add(AlertRecipient(name=request.form['name'], email=request.form['email']))
        db.session.commit(); flash('Destinatário adicionado.', 'success')
    return render_template('admin/alerts.html', alerts=build_oil_alerts(), recipients=AlertRecipient.query.order_by(AlertRecipient.name).all())

@main_bp.route('/admin/alerts/send', methods=['POST'])
@login_required
@admin_required
def alerts_send():
    alerts = build_oil_alerts()
    sent = send_alert_email(alerts)
    flash('Alertas enviados.' if sent else 'Configure SMTP e destinatários para enviar os alertas.', 'success' if sent else 'warning')
    return redirect(url_for('main.alerts'))

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

def send_alert_email(alerts):
    host=os.getenv('MAIL_HOST'); user=os.getenv('MAIL_USER'); password=os.getenv('MAIL_PASSWORD'); sender=os.getenv('MAIL_FROM') or user
    recipients=[r.email for r in AlertRecipient.query.filter_by(active=True).all()]
    if not recipients: recipients=[e.strip() for e in os.getenv('ALERT_EMAILS','').split(',') if e.strip()]
    if not host or not sender or not recipients or not alerts: return False
    msg=EmailMessage(); msg['Subject']='Favela Llog Controle de Veículos — Alertas'; msg['From']=sender; msg['To']=', '.join(recipients)
    msg.set_content('\n\n'.join(f"{a['title']}\n{a['vehicle'].plate} - {a['vehicle'].brand} {a['vehicle'].model}\n{a['detail']}" for a in alerts))
    with smtplib.SMTP(host, int(os.getenv('MAIL_PORT','587'))) as smtp:
        smtp.starttls()
        if user: smtp.login(user,password)
        smtp.send_message(msg)
    return True
