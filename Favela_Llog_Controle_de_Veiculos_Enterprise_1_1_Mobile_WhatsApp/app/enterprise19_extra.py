import json
from flask import flash, redirect, request
from flask_login import current_user

from .models import User, VehicleIssue

ITEMS = [
    ('tires_ok','Pneus'),('brakes_ok','Freios'),('lights_ok','Luzes'),('indicators_ok','Setas'),
    ('mirrors_ok','Retrovisores'),('horn_ok','Buzina'),('chain_ok','Corrente'),('charger_ok','Carregador'),
    ('phone_holder_ok','Suporte de celular'),('top_case_ok','Baú'),('saddlebags_ok','Alforje')
]


def _extra_context():
    if not current_user.is_authenticated:
        return {}
    from .enterprise18 import enterprise18_context, _oil_status
    from .enterprise19 import active_vehicle
    from .routes import build_oil_statuses

    admins_q = User.query.filter(User.role.in_(('ADMIN','ADMIN_GLOBAL','ADMIN_BASE')), User.active.is_(True))
    all_base_admins = admins_q.order_by(User.name).all()
    manager_open_issues = []
    if current_user.is_admin:
        q = VehicleIssue.query.filter_by(status='OPEN')
        if current_user.is_base_admin:
            q = q.filter_by(base_code=current_user.base_code)
        manager_open_issues = q.order_by(VehicleIssue.created_at.desc()).limit(30).all()

    v = active_vehicle()
    active_oil = build_oil_statuses(v.id) if v and v.vehicle_type == 'MOTORCYCLE' else []

    # O alerta fixo do topo também precisa acompanhar a moto realmente usada na sessão.
    e18_data = enterprise18_context().get('e18')
    if e18_data and current_user.role == 'DRIVER' and v:
        e18_data = dict(e18_data)
        e18_data['oil'] = _oil_status(v)

    return {
        'all_base_admins': all_base_admins,
        'manager_open_issues': manager_open_issues,
        'active_vehicle_oil_statuses': active_oil,
        'active_vehicle_oil_status': active_oil[0] if active_oil else None,
        'e18': e18_data,
    }


def attention_notes_list(raw):
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [(v.get('label', k), v.get('reason', '')) for k, v in data.items()]
    except Exception:
        return []


def init_enterprise19_extra(app):
    app.jinja_env.filters['attention_notes_list'] = attention_notes_list
    app.context_processor(_extra_context)

    @app.before_request
    def validate_enterprise19_forms():
        if not current_user.is_authenticated or request.method != 'POST':
            return None
        if request.endpoint == 'main.checklist_new':
            missing = []
            for field, label in ITEMS:
                if request.form.get(field) == 'attention' and not (request.form.get(field + '_reason') or '').strip():
                    missing.append(label)
            if request.form.get('general_condition') in ('ATTENTION','MAINTENANCE') and not (request.form.get('general_condition_reason') or '').strip():
                missing.append('Estado geral')
            if missing:
                flash('Informe o motivo para todos os itens marcados como Atenção: ' + ', '.join(missing) + '.', 'danger')
                return redirect(request.url)
        return None
