from collections import OrderedDict
from types import SimpleNamespace

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
            groups[key] = []
        groups[key].append(issue)

    compact = []
    for issues in groups.values():
        latest = issues[0]
        summary = ' • '.join(
            f'{row.item_label} — {row.description}' for row in issues[:3]
        )
        if len(issues) > 3:
            summary += f' • +{len(issues) - 3} pendência(s)'
        compact.append(SimpleNamespace(
            id=latest.id,
            vehicle=latest.vehicle,
            base_code=latest.base_code,
            reported_by=latest.reported_by,
            created_at=latest.created_at,
            item_label=f'{len(issues)} pendência' + ('s' if len(issues) != 1 else ''),
            description=summary,
            issue_count=len(issues),
        ))
    return compact


def vehicle_cards_v31_context():
    grouped = grouped_manager_issues()
    return {
        # Sobrescreve a lista anterior do context processor para que o template
        # existente passe a renderizar um único card compacto por moto.
        'manager_open_issues': grouped,
        'manager_issue_groups': grouped,
    }


def init_vehicle_dashboard_cards_v31(app):
    app.context_processor(vehicle_cards_v31_context)
