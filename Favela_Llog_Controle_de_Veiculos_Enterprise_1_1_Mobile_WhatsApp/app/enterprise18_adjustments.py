from urllib.parse import quote

from flask import request, url_for
from flask_login import current_user

from .models import db, Vehicle, DailyChecklist
from .time_utils import local_today


def _phone(value):
    digits = ''.join(c for c in (value or '') if c.isdigit())
    return ('55' + digits) if len(digits) in (10, 11) else digits


def _selected_vehicle_any_same_base(prefer_active_checklist=False):
    """Permite ao motorista abastecer qualquer moto da própria base."""
    vehicle_id = (
        request.form.get('motorcycle_vehicle_id', type=int)
        or request.form.get('vehicle_id', type=int)
        or request.args.get('vehicle_id', type=int)
    )
    if vehicle_id:
        vehicle = db.session.get(Vehicle, vehicle_id)
        if vehicle and vehicle.vehicle_type == 'MOTORCYCLE':
            if current_user.is_global_admin or vehicle.base_code == current_user.base_code:
                return vehicle
            return None
    if prefer_active_checklist and not current_user.is_admin:
        from .routes import active_checklist_for_driver
        active = active_checklist_for_driver(current_user)
        if active:
            return active.vehicle
    vehicle = current_user.vehicle
    return vehicle if vehicle and vehicle.vehicle_type == 'MOTORCYCLE' else None


def _owner_only_whatsapp_links(alerts, recipients):
    """Alerta de óleo vai para o responsável da moto, sem lista genérica de contatos."""
    from .routes import whatsapp_message
    for alert in alerts:
        alert['whatsapp_links'] = []
        owner = alert['vehicle'].driver
        if owner and owner.active and owner.phone:
            phone = _phone(owner.phone)
            if phone:
                alert['whatsapp_links'].append({
                    'name': owner.name,
                    'url': f"https://wa.me/{phone}?text={quote(whatsapp_message(alert))}",
                })
    return alerts


def _extra_context():
    if not getattr(current_user, 'is_authenticated', False):
        return {}
    fuel_motorcycles = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE').order_by(Vehicle.plate).all()
    borrowed_owner_alert = None
    if current_user.role == 'DRIVER':
        borrowed = DailyChecklist.query.filter(
            DailyChecklist.owner_driver_id == current_user.id,
            DailyChecklist.driver_id != current_user.id,
            DailyChecklist.borrowed_vehicle.is_(True),
            DailyChecklist.checklist_date == local_today(),
            DailyChecklist.is_deleted.is_(False),
        ).order_by(DailyChecklist.created_at.desc()).first()
        if borrowed:
            action = 'devolveu' if borrowed.checklist_type == 'DEVOLUCAO' else 'retirou'
            borrowed_owner_alert = {
                'title': f'Sua moto foi utilizada por {borrowed.driver.name}',
                'text': f'{borrowed.driver.name} {action} a moto {borrowed.vehicle.plate} hoje. KM registrado: {borrowed.odometer}.',
                'url': url_for('main.checklist_share', token=borrowed.share_token),
            }
    return {'fuel_motorcycles': fuel_motorcycles, 'borrowed_owner_alert': borrowed_owner_alert}


def init_adjustments(app):
    from . import routes
    routes.selected_vehicle = _selected_vehicle_any_same_base
    routes.attach_whatsapp_links = _owner_only_whatsapp_links
    app.context_processor(_extra_context)
