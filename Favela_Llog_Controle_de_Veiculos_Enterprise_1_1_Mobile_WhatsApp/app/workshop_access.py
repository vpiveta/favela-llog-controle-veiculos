from flask import redirect, request, url_for
from flask_login import current_user


def init_workshop_access(app):
    """Perfil OFICINA: acesso somente ao lançamento de manutenção e conta."""
    allowed = {
        'auth.logout',
        'main.maintenance_new',
        'main.maintenance_dashboard',
        'main.maintenance_part_new',
        'main.maintenance_catalog_new',
        'main.maintenance_catalog',
        'main.maintenance_monthly_report',
        'main.maintenance_monitor',
        'production.change_password',
        'static',
    }

    @app.before_request
    def workshop_only():
        if not current_user.is_authenticated:
            return None
        # Motoristas não lançam mais manutenção; somente consultam o status da própria moto.
        if current_user.role == 'DRIVER' and request.endpoint == 'main.maintenance_new':
            return redirect(url_for('main.maintenance_monitor'))
        if current_user.role != 'WORKSHOP':
            return None
        endpoint = request.endpoint or ''
        if endpoint in allowed or endpoint.startswith('static'):
            return None
        return redirect(url_for('main.maintenance_new'))
