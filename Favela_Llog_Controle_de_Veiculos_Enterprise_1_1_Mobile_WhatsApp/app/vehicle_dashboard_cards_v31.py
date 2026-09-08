from collections import OrderedDict

from flask_login import current_user
from sqlalchemy.orm import selectinload

from .models import VehicleIssue


def grouped_manager_issues():
    """Agrupa pendências abertas por veículo para cards compactos no painel."""
    if not current_user.is_authenticated or not current_user.is_admin:
        return []

    q = VehicleIssue.query.options(
        selectinload(VehicleIssue.vehicle),
        selectinload(VehicleIssue.reported_by),
    ).filter(VehicleIssue.status.in_(('OPEN', 'SCHEDULED', 'AUTHORIZED')))
    if current_user.is_base_admin:
        q = q.filter_by(base_code=current_user.base_code)

    rows = q.order_by(VehicleIssue.created_at.desc(), VehicleIssue.id.desc()).limit(100).all()
    groups = OrderedDict()
    for issue in rows:
        key = issue.vehicle_id
        if key not in groups:
            groups[key] = {
                'vehicle': issue.vehicle,
                'issues': [],
                'latest': issue,
            }
        groups[key]['issues'].append(issue)

    return list(groups.values())


def vehicle_cards_v31_context():
    return {
        'manager_issue_groups': grouped_manager_issues(),
    }


def init_vehicle_dashboard_cards_v31(app):
    app.context_processor(vehicle_cards_v31_context)
