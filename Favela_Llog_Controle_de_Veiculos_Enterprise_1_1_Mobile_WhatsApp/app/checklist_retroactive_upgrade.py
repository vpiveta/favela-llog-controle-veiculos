from datetime import timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

from .models import db, User, DailyChecklist, AuditLog
from .time_utils import local_today, utc_now


class ChecklistRetroRelease(db.Model):
    __tablename__ = 'checklist_retro_release'
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    base_code = db.Column(db.String(10), nullable=False, default='SDA9', index=True)
    missed_date = db.Column(db.Date, nullable=False, index=True)
    missing_types = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='OPEN', index=True)
    released_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    released_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    completed_at = db.Column(db.DateTime)
    note = db.Column(db.Text)

    driver = db.relationship('User', foreign_keys=[driver_id])
    released_by = db.relationship('User', foreign_keys=[released_by_id])

    __table_args__ = (
        db.UniqueConstraint('driver_id', 'missed_date', name='uq_checklist_retro_driver_date'),
    )


def _missing_types(driver_id, day):
    rows = DailyChecklist.query.filter_by(
        driver_id=driver_id,
        checklist_date=day,
        is_deleted=False,
    ).with_entities(DailyChecklist.checklist_type).all()
    kinds = {row[0] for row in rows}
    missing = []
    if 'RETIRADA' not in kinds:
        missing.append('RETIRADA')
    if 'DEVOLUCAO' not in kinds:
        missing.append('DEVOLUCAO')
    return missing


def _allowed_admin_release(row):
    if not current_user.is_admin:
        return False
    return current_user.is_global_admin or row.base_code == current_user.base_code


def _admin_releases():
    if not current_user.is_admin:
        abort(403)

    days_back = request.args.get('days', default=30, type=int) or 30
    days_back = max(7, min(days_back, 90))
    today = local_today()
    start = today - timedelta(days=days_back)

    uq = User.query.filter_by(role='DRIVER', active=True)
    if current_user.is_base_admin:
        uq = uq.filter_by(base_code=current_user.base_code)
    drivers = uq.order_by(User.name).all()

    existing_q = DailyChecklist.query.filter(
        DailyChecklist.is_deleted.is_(False),
        DailyChecklist.checklist_date >= start,
        DailyChecklist.checklist_date < today,
    )
    if current_user.is_base_admin:
        existing_q = existing_q.filter(DailyChecklist.base_code == current_user.base_code)
    existing = existing_q.with_entities(
        DailyChecklist.driver_id,
        DailyChecklist.checklist_date,
        DailyChecklist.checklist_type,
    ).all()
    done = {}
    for driver_id, checklist_date, checklist_type in existing:
        done.setdefault((driver_id, checklist_date), set()).add(checklist_type)

    release_q = ChecklistRetroRelease.query.filter(
        ChecklistRetroRelease.missed_date >= start,
        ChecklistRetroRelease.missed_date < today,
    )
    if current_user.is_base_admin:
        release_q = release_q.filter_by(base_code=current_user.base_code)
    releases = {(r.driver_id, r.missed_date): r for r in release_q.all()}

    rows = []
    day = today - timedelta(days=1)
    while day >= start:
        for driver in drivers:
            kinds = done.get((driver.id, day), set())
            missing = []
            if 'RETIRADA' not in kinds:
                missing.append('RETIRADA')
            if 'DEVOLUCAO' not in kinds:
                missing.append('DEVOLUCAO')
            if missing:
                rows.append({
                    'driver': driver,
                    'day': day,
                    'missing': missing,
                    'release': releases.get((driver.id, day)),
                })
        day -= timedelta(days=1)

    return render_template(
        'admin/checklist_releases.html',
        rows=rows,
        days_back=days_back,
        today=today,
    )


def _release_day():
    if not current_user.is_admin:
        abort(403)
    driver = db.session.get(User, request.form.get('driver_id', type=int)) or abort(404)
    if current_user.is_base_admin and driver.base_code != current_user.base_code:
        abort(403)
    try:
        day = __import__('datetime').datetime.strptime(request.form.get('day', ''), '%Y-%m-%d').date()
    except Exception:
        abort(400)
    if day >= local_today():
        flash('A liberação retroativa é somente para dias anteriores.', 'warning')
        return redirect(url_for('checklist_retro_admin'))

    missing = _missing_types(driver.id, day)
    if not missing:
        flash('Esse motorista já realizou os checklists desse dia.', 'info')
        return redirect(url_for('checklist_retro_admin'))

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
    db.session.add(AuditLog(
        action='CHECKLIST_RETRO_RELEASE',
        entity_type='CHECKLIST_RETRO_RELEASE',
        entity_id=row.id,
        description=f'{current_user.name} liberou checklist retroativo de {driver.name} referente a {day.strftime("%d/%m/%Y")}: {", ".join(missing)}.',
        base_code=driver.base_code,
        user_id=current_user.id,
    ))
    db.session.commit()
    flash(f'Checklist de {day.strftime("%d/%m/%Y")} liberado para {driver.name}.', 'success')
    return redirect(url_for('checklist_retro_admin'))


def _cancel_release(release_id):
    row = db.session.get(ChecklistRetroRelease, release_id) or abort(404)
    if not _allowed_admin_release(row):
        abort(403)
    row.status = 'CANCELLED'
    db.session.add(AuditLog(
        action='CHECKLIST_RETRO_CANCEL',
        entity_type='CHECKLIST_RETRO_RELEASE',
        entity_id=row.id,
        description=f'{current_user.name} cancelou a liberação retroativa de {row.driver.name} em {row.missed_date.strftime("%d/%m/%Y")}.',
        base_code=row.base_code,
        user_id=current_user.id,
    ))
    db.session.commit()
    flash('Liberação cancelada.', 'success')
    return redirect(url_for('checklist_retro_admin'))


def _driver_releases():
    if current_user.role != 'DRIVER':
        return redirect(url_for('checklist_retro_admin'))
    releases = ChecklistRetroRelease.query.filter_by(
        driver_id=current_user.id,
        status='OPEN',
    ).order_by(ChecklistRetroRelease.missed_date.desc()).all()
    items = []
    for release in releases:
        missing = _missing_types(current_user.id, release.missed_date)
        if not missing:
            release.status = 'COMPLETED'
            release.completed_at = utc_now()
            continue
        release.missing_types = ','.join(missing)
        items.append({'release': release, 'missing': missing})
    db.session.commit()
    return render_template('driver/checklist_releases.html', items=items)


def _active_checklist_date_order(user):
    latest = DailyChecklist.query.filter_by(
        driver_id=user.id, is_deleted=False
    ).order_by(
        DailyChecklist.checklist_date.desc(),
        DailyChecklist.created_at.desc(),
        DailyChecklist.id.desc(),
    ).first()
    if not latest or latest.checklist_type != 'RETIRADA':
        return None
    return latest


def init_checklist_retroactive_upgrade(app):
    app.add_url_rule('/admin/checklists/liberacoes', 'checklist_retro_admin', login_required(_admin_releases), methods=['GET'])
    app.add_url_rule('/admin/checklists/liberar-dia', 'checklist_retro_release_day', login_required(_release_day), methods=['POST'])
    app.add_url_rule('/admin/checklists/liberacoes/<int:release_id>/cancelar', 'checklist_retro_cancel', login_required(_cancel_release), methods=['POST'])
    app.add_url_rule('/checklists/liberados', 'checklist_retro_driver', login_required(_driver_releases), methods=['GET'])

    from . import routes as routes_module
    routes_module.active_checklist_for_driver = _active_checklist_date_order
    original_checklist_new = app.view_functions.get('main.checklist_new')

    if original_checklist_new:
        def retro_checklist_new(*args, **kwargs):
            release_id = request.args.get('release_id', type=int)
            if not release_id:
                return original_checklist_new(*args, **kwargs)
            release = db.session.get(ChecklistRetroRelease, release_id) or abort(404)
            if current_user.role != 'DRIVER' or release.driver_id != current_user.id or release.status != 'OPEN':
                abort(403)
            if release.missed_date >= local_today():
                abort(400)
            requested_type = ((request.form.get('checklist_type') if request.method == 'POST' else request.args.get('type')) or 'RETIRADA').upper()
            missing_before = _missing_types(current_user.id, release.missed_date)
            if requested_type not in missing_before:
                flash('Esse tipo de checklist não está pendente para a data liberada.', 'warning')
                return redirect(url_for('checklist_retro_driver'))

            original_local_today = routes_module.local_today
            routes_module.local_today = lambda: release.missed_date
            try:
                response = original_checklist_new(*args, **kwargs)
            finally:
                routes_module.local_today = original_local_today

            if request.method == 'POST':
                missing_after = _missing_types(current_user.id, release.missed_date)
                release.missing_types = ','.join(missing_after)
                if not missing_after:
                    release.status = 'COMPLETED'
                    release.completed_at = utc_now()
                db.session.commit()
            return response

        app.view_functions['main.checklist_new'] = login_required(retro_checklist_new)

    @app.context_processor
    def retro_checklist_context():
        if not current_user.is_authenticated:
            return {'retro_checklist_open_count': 0}
        if current_user.role == 'DRIVER':
            count = ChecklistRetroRelease.query.filter_by(driver_id=current_user.id, status='OPEN').count()
            return {'retro_checklist_open_count': count}
        return {'retro_checklist_open_count': 0}
