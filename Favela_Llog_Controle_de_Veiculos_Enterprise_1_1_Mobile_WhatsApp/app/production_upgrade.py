from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from markupsafe import escape
from sqlalchemy import or_

from .models import db, User, Vehicle, Expense, DailyChecklist, AuditLog
from .time_utils import local_today, utc_now
from .enterprise18 import BASES, current_base, is_global_admin

production_bp = Blueprint('production', __name__)


class DriverExpenseRead(db.Model):
    __tablename__ = 'driver_expense_read'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expense.id'), nullable=False, index=True)
    read_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    user = db.relationship('User')
    expense = db.relationship('Expense')
    __table_args__ = (db.UniqueConstraint('user_id', 'expense_id', name='uq_driver_expense_read'),)


def _month_bounds(raw=None):
    today = local_today()
    raw = (raw or '').strip()
    try:
        year, month = [int(x) for x in raw.split('-', 1)]
        start = date(year, month, 1)
    except Exception:
        start = date(today.year, today.month, 1)
    end = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    prev = date(start.year - 1, 12, 1) if start.month == 1 else date(start.year, start.month - 1, 1)
    return start, end, prev


def _month_label(start):
    names = ('Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro')
    return f'{names[start.month-1]} {start.year}'


def _selected_base():
    if is_global_admin():
        raw = (request.args.get('base') or 'ALL').upper().strip()
        return raw if raw in BASES else 'ALL'
    return current_base() or getattr(current_user, 'base_code', 'SDA9')


def _expense_scope(start=None, end=None, base_code=None):
    q = Expense.query.filter(Expense.asset_type == 'MOTORCYCLE', Expense.is_deleted.is_(False))
    if start is not None:
        q = q.filter(Expense.expense_date >= start)
    if end is not None:
        q = q.filter(Expense.expense_date < end)
    if base_code and base_code != 'ALL':
        q = q.filter(Expense.base_code == base_code)
    if not current_user.is_admin:
        if current_user.vehicle:
            q = q.filter(Expense.vehicle_id == current_user.vehicle.id)
        else:
            q = q.filter(Expense.id == -1)
    return q


def _vehicle_scope(base_code=None):
    q = Vehicle.query.filter(Vehicle.vehicle_type == 'MOTORCYCLE')
    if base_code and base_code != 'ALL':
        q = q.filter(Vehicle.base_code == base_code)
    if not current_user.is_admin:
        if current_user.vehicle:
            q = q.filter(Vehicle.id == current_user.vehicle.id)
        else:
            q = q.filter(Vehicle.id == -1)
    return q


def _money_total(rows, kind=None):
    return sum((Decimal(e.amount) for e in rows if kind is None or e.expense_type == kind), Decimal('0'))


def _unread_driver_expenses(limit=5):
    if not current_user.is_authenticated or current_user.role != 'DRIVER' or not current_user.vehicle:
        return []
    since = utc_now() - timedelta(days=45)
    read_ids = db.session.query(DriverExpenseRead.expense_id).filter(DriverExpenseRead.user_id == current_user.id)
    q = Expense.query.join(User, Expense.created_by_id == User.id).filter(
        Expense.vehicle_id == current_user.vehicle.id,
        Expense.asset_type == 'MOTORCYCLE',
        Expense.is_deleted.is_(False),
        Expense.created_at >= since,
        User.role.in_(('ADMIN', 'ADMIN_GLOBAL', 'ADMIN_BASE')),
        ~Expense.id.in_(read_ids),
    )
    return q.order_by(Expense.created_at.desc(), Expense.id.desc()).limit(limit).all()


@production_bp.route('/minha-senha', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password') or ''
        new_password = request.form.get('new_password') or ''
        confirm = request.form.get('confirm_password') or ''
        try:
            if not current_user.check_password(current_password):
                raise ValueError('A senha atual está incorreta.')
            if len(new_password) < 6:
                raise ValueError('A nova senha deve ter pelo menos 6 caracteres.')
            if new_password != confirm:
                raise ValueError('A confirmação da nova senha não confere.')
            if current_user.check_password(new_password):
                raise ValueError('Escolha uma senha diferente da atual.')
            current_user.set_password(new_password)
            current_user.must_change_password = False
            db.session.add(AuditLog(
                action='CHANGE_PASSWORD', entity_type='USER', entity_id=current_user.id,
                description='Senha alterada pelo próprio usuário.',
                base_code=current_user.base_code, user_id=current_user.id,
            ))
            db.session.commit()
            flash('Senha alterada com sucesso.', 'success')
            return redirect(url_for('main.dashboard'))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    return render_template('auth/change_password.html', first_access=bool(current_user.must_change_password))


@production_bp.route('/esqueci-minha-senha', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('production.change_password'))
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        cnh = ''.join(c for c in (request.form.get('cnh_number') or '') if c.isdigit())
        new_password = request.form.get('new_password') or ''
        confirm = request.form.get('confirm_password') or ''
        try:
            user = User.query.filter_by(username=username, active=True).first()
            if not user or user.role != 'DRIVER':
                raise ValueError('Não foi possível validar os dados informados.')
            from .enterprise19_wait import DriverDocument
            doc = DriverDocument.query.filter_by(user_id=user.id).first()
            if not doc or doc.cnh_number != cnh:
                raise ValueError('Usuário ou CNH não conferem.')
            if len(new_password) < 6:
                raise ValueError('A nova senha deve ter pelo menos 6 caracteres.')
            if new_password != confirm:
                raise ValueError('A confirmação da nova senha não confere.')
            user.set_password(new_password)
            user.must_change_password = False
            db.session.add(AuditLog(
                action='RECOVER_PASSWORD', entity_type='USER', entity_id=user.id,
                description='Senha recuperada pelo próprio motorista com validação da CNH.',
                base_code=user.base_code, user_id=user.id,
            ))
            db.session.commit()
            flash('Senha redefinida. Entre com a nova senha.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    return render_template('auth/forgot_password.html')


@production_bp.post('/alerta-gasto/<int:expense_id>/lido')
@login_required
def expense_alert_read(expense_id):
    if current_user.role != 'DRIVER':
        abort(403)
    expense = db.session.get(Expense, expense_id) or abort(404)
    if not current_user.vehicle or expense.vehicle_id != current_user.vehicle.id:
        abort(403)
    exists = DriverExpenseRead.query.filter_by(user_id=current_user.id, expense_id=expense.id).first()
    if not exists:
        db.session.add(DriverExpenseRead(user_id=current_user.id, expense_id=expense.id))
        db.session.commit()
    return redirect(request.referrer or url_for('main.dashboard'))


@production_bp.route('/relatorio-mensal')
@login_required
def monthly_report():
    start, end, prev = _month_bounds(request.args.get('month'))
    base_code = _selected_base()
    rows = _expense_scope(start, end, base_code).order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    previous_rows = _expense_scope(prev, start, base_code).all()
    total = _money_total(rows)
    previous_total = _money_total(previous_rows)
    fuel = _money_total(rows, 'FUEL')
    maintenance = _money_total(rows, 'MAINTENANCE')
    delta = None
    if previous_total > 0:
        delta = ((total - previous_total) / previous_total * Decimal('100')).quantize(Decimal('0.1'))

    grouped = {}
    drivers = {}
    for e in rows:
        item = grouped.setdefault(e.vehicle_id, {
            'vehicle': e.vehicle, 'total': Decimal('0'), 'fuel': Decimal('0'),
            'maintenance': Decimal('0'), 'count': 0,
        })
        item['total'] += Decimal(e.amount)
        item['count'] += 1
        if e.expense_type == 'FUEL': item['fuel'] += Decimal(e.amount)
        if e.expense_type == 'MAINTENANCE': item['maintenance'] += Decimal(e.amount)
        driver = e.responsible_driver or e.vehicle.driver
        if driver:
            d = drivers.setdefault(driver.id, {'driver': driver, 'total': Decimal('0'), 'count': 0})
            d['total'] += Decimal(e.amount)
            d['count'] += 1

    by_vehicle = sorted(grouped.values(), key=lambda x: x['total'], reverse=True)
    by_driver = sorted(drivers.values(), key=lambda x: x['total'], reverse=True)
    vehicles = _vehicle_scope(base_code).count()
    checklist_q = DailyChecklist.query.filter(
        DailyChecklist.checklist_date >= start,
        DailyChecklist.checklist_date < end,
        DailyChecklist.is_deleted.is_(False),
    )
    if base_code != 'ALL':
        checklist_q = checklist_q.filter(DailyChecklist.base_code == base_code)
    if not current_user.is_admin:
        checklist_q = checklist_q.filter(DailyChecklist.driver_id == current_user.id)

    return render_template(
        'reports/monthly.html', month=start.strftime('%Y-%m'), month_label=_month_label(start),
        base_code=base_code, bases=BASES, is_global=is_global_admin(),
        total=total, previous_total=previous_total, delta=delta, fuel=fuel,
        maintenance=maintenance, vehicles=vehicles, checklist_count=checklist_q.count(),
        by_vehicle=by_vehicle, by_driver=by_driver, rows=rows,
    )


@production_bp.route('/buscar')
@login_required
def search():
    term = (request.args.get('q') or '').strip()
    base_code = _selected_base()
    vehicles = []
    drivers = []
    if term:
        like = f'%{term}%'
        vq = _vehicle_scope(base_code).filter(or_(
            Vehicle.plate.ilike(like), Vehicle.brand.ilike(like), Vehicle.model.ilike(like)
        ))
        vehicles = vq.order_by(Vehicle.plate).limit(30).all()
        if current_user.is_admin:
            uq = User.query.filter(User.role == 'DRIVER').filter(or_(User.name.ilike(like), User.username.ilike(like)))
            if base_code != 'ALL':
                uq = uq.filter(User.base_code == base_code)
            drivers = uq.order_by(User.name).limit(30).all()
    return render_template('search.html', term=term, vehicles=vehicles, drivers=drivers, base_code=base_code, bases=BASES, is_global=is_global_admin())


@production_bp.route('/moto/<int:vehicle_id>')
@login_required
def vehicle_history(vehicle_id):
    vehicle = db.session.get(Vehicle, vehicle_id) or abort(404)
    if vehicle.vehicle_type != 'MOTORCYCLE':
        abort(404)
    if not current_user.is_global_admin and vehicle.base_code != current_user.base_code:
        abort(403)
    if not current_user.is_admin and (not current_user.vehicle or current_user.vehicle.id != vehicle.id):
        abort(403)
    start, end, _ = _month_bounds(request.args.get('month'))
    expenses = _expense_scope(start, end, vehicle.base_code).filter(Expense.vehicle_id == vehicle.id).order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    uses = DailyChecklist.query.filter(
        DailyChecklist.vehicle_id == vehicle.id,
        DailyChecklist.checklist_date >= start,
        DailyChecklist.checklist_date < end,
        DailyChecklist.is_deleted.is_(False),
    ).order_by(DailyChecklist.created_at.desc()).all()
    total = _money_total(expenses)
    fuel = _money_total(expenses, 'FUEL')
    maintenance = _money_total(expenses, 'MAINTENANCE')
    from .enterprise19_wait import get_driver_cnh
    return render_template(
        'vehicle_history.html', vehicle=vehicle, month=start.strftime('%Y-%m'),
        month_label=_month_label(start), expenses=expenses, uses=uses,
        total=total, fuel=fuel, maintenance=maintenance,
        owner_cnh=get_driver_cnh(vehicle.driver_id) if vehicle.driver_id else None,
    )


def init_production_upgrade(app):
    app.register_blueprint(production_bp)

    @app.before_request
    def production_rules():
        endpoint = request.endpoint or ''
        if current_user.is_authenticated and current_user.must_change_password:
            allowed = {'production.change_password', 'auth.logout', 'static'}
            if endpoint not in allowed:
                return redirect(url_for('production.change_password'))

        if endpoint == 'main.fuel_new':
            if request.method == 'GET' and (request.args.get('type') or '').upper() == 'CAR':
                flash('O controle foi padronizado somente para motos.', 'warning')
                return redirect(url_for('main.fuel_new', type='MOTORCYCLE'))
            if request.method == 'POST' and (request.form.get('vehicle_type') or 'MOTORCYCLE').upper() == 'CAR':
                flash('Novos lançamentos de carro foram desativados. Utilize somente motos.', 'danger')
                return redirect(url_for('main.fuel_new', type='MOTORCYCLE'))

        if endpoint == 'main.vehicles' and request.method == 'POST' and (request.form.get('vehicle_type') or 'MOTORCYCLE').upper() == 'CAR':
            flash('O cadastro de carros foi desativado. O sistema agora trabalha somente com motos.', 'danger')
            return redirect(url_for('main.vehicles'))
        return None

    @app.context_processor
    def production_context():
        from .enterprise19_wait import get_driver_cnh
        return {'get_driver_cnh': get_driver_cnh}

    @app.after_request
    def inject_production_ui(response):
        if response.mimetype != 'text/html':
            return response
        try:
            html = response.get_data(as_text=True)
            css = '<link rel="stylesheet" href="%s">' % url_for('static', filename='css/production_refresh.css')
            js = '<script src="%s"></script>' % url_for('static', filename='js/production_refresh.js')
            if '</head>' in html and 'production_refresh.css' not in html:
                html = html.replace('</head>', css + '</head>', 1)
            if '</body>' in html and 'production_refresh.js' not in html:
                html = html.replace('</body>', js + '</body>', 1)

            if current_user.is_authenticated and '</nav>' in html and 'Relatório mensal' not in html:
                links = '<hr><small class="muted">CONTROLE</small>'
                links += f'<a href="{url_for("production.search")}">🔎 Buscar moto/motorista</a>'
                links += f'<a href="{url_for("production.monthly_report")}">📊 Relatório mensal</a>'
                links += f'<a href="{url_for("production.change_password")}">🔐 Alterar senha</a>'
                html = html.replace('</nav>', links + '</nav>', 1)

            if current_user.is_authenticated and current_user.role == 'DRIVER' and '<main class="content">' in html:
                alerts = _unread_driver_expenses()
                if alerts:
                    cards = ['<section class="driver-cost-alerts panel"><div class="section-head"><div><h3>Atualizações da sua moto</h3><p class="muted">Manutenções e abastecimentos lançados pela gestão.</p></div><span class="count-pill">%d nova(s)</span></div>' % len(alerts)]
                    for e in alerts:
                        kind = 'Abastecimento' if e.expense_type == 'FUEL' else 'Manutenção'
                        detail = e.maintenance.description if e.maintenance else (e.fuel.station if e.fuel and e.fuel.station else 'Lançamento registrado')
                        cards.append(
                            '<article class="driver-cost-alert"><div><b>%s · %s</b><span>%s · R$ %s · %s</span><small>Lançado por %s</small></div>'
                            '<form method="post" action="%s"><button class="btn compact">Marcar como visto</button></form></article>' % (
                                escape(kind), escape(e.vehicle.plate), escape(e.expense_date.strftime('%d/%m/%Y')),
                                str(e.amount).replace('.', ','), escape(detail or '-'), escape(e.created_by.name),
                                url_for('production.expense_alert_read', expense_id=e.id)
                            )
                        )
                    cards.append('</section>')
                    html = html.replace('<main class="content">', '<main class="content">' + ''.join(cards), 1)
            response.set_data(html)
        except Exception:
            app.logger.exception('Falha ao aplicar melhorias visuais de produção')
        return response
