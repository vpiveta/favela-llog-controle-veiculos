from datetime import datetime

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user, login_required

from .models import db, User, AuditLog
from .time_utils import local_today, utc_now
from .checklist_retroactive_upgrade import ChecklistRetroRelease, _missing_types


def _release_day_fixed():
    if not current_user.is_admin:
        abort(403)

    driver = db.session.get(User, request.form.get('driver_id', type=int)) or abort(404)
    if current_user.is_base_admin and driver.base_code != current_user.base_code:
        abort(403)

    try:
        day = datetime.strptime(request.form.get('day', ''), '%Y-%m-%d').date()
    except Exception:
        abort(400)

    if day >= local_today():
        flash('A liberação retroativa é somente para dias anteriores.', 'warning')
        return redirect(url_for('checklist_retro_admin'))

    missing = _missing_types(driver.id, day)
    if not missing:
        flash('Esse motorista já realizou os checklists desse dia.', 'info')
        return redirect(url_for('checklist_retro_admin'))

    try:
        row = ChecklistRetroRelease.query.filter_by(driver_id=driver.id, missed_date=day).first()
        if not row:
            row = ChecklistRetroRelease(
                driver_id=driver.id,
                base_code=driver.base_code,
                missed_date=day,
                missing_types=','.join(missing),
                released_by_id=current_user.id,
            )
            db.session.add(row)
        else:
            row.missing_types = ','.join(missing)
            row.status = 'OPEN'
            row.released_by_id = current_user.id
            row.released_at = utc_now()
            row.completed_at = None

        row.note = (request.form.get('note') or '').strip() or None

        # Garante que o registro tenha ID antes de criar a auditoria.
        db.session.flush()

        db.session.add(AuditLog(
            action='CHECKLIST_RETRO_RELEASE',
            entity_type='CHECKLIST_RETRO_RELEASE',
            entity_id=row.id,
            description=(
                f'{current_user.name} liberou checklist retroativo de {driver.name} '
                f'referente a {day.strftime("%d/%m/%Y")}: {", ".join(missing)}.'
            ),
            base_code=driver.base_code,
            user_id=current_user.id,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    flash(f'Checklist de {day.strftime("%d/%m/%Y")} liberado para {driver.name}.', 'success')
    return redirect(url_for('checklist_retro_admin'))


def init_checklist_retroactive_hotfix(app):
    # Substitui apenas a ação POST de liberação; as demais rotas permanecem intactas.
    app.view_functions['checklist_retro_release_day'] = login_required(_release_day_fixed)
