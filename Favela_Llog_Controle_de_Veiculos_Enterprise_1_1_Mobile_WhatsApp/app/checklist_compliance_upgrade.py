from datetime import date, timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import extract, func
from sqlalchemy.orm import selectinload

from .models import db, User, DailyChecklist, Expense, AdminNotification, AuditLog
from .time_utils import local_today, utc_now

MONTHS_PT = ('Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro')


class ChecklistComplianceCase(db.Model):
    __tablename__ = 'checklist_compliance_case'
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    base_code = db.Column(db.String(10), nullable=False, default='SDA9', index=True)
    missed_date = db.Column(db.Date, nullable=False, index=True)
    missing_types = db.Column(db.String(80), nullable=False)
    justification = db.Column(db.Text)
    consecutive_count = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(30), nullable=False, default='WAITING_JUSTIFICATION', index=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    justified_at = db.Column(db.DateTime)
    decided_at = db.Column(db.DateTime)
    decided_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    decision_note = db.Column(db.Text)
    driver = db.relationship('User', foreign_keys=[driver_id])
    decided_by = db.relationship('User', foreign_keys=[decided_by_id])
    __table_args__ = (db.UniqueConstraint('driver_id','missed_date', name='uq_checklist_compliance_driver_date'),)


def _missing_types(driver_id, day):
    rows = DailyChecklist.query.filter_by(driver_id=driver_id, checklist_date=day, is_deleted=False).with_entities(DailyChecklist.checklist_type).all()
    kinds = {r[0] for r in rows}
    missing=[]
    if 'RETIRADA' not in kinds: missing.append('RETIRADA')
    if 'DEVOLUCAO' not in kinds: missing.append('DEVOLUCAO')
    return missing


def _ensure_cases(user):
    """Cria pendências somente para dias já encerrados; nunca bloqueia pelo dia atual."""
    today = local_today()
    days = [today - timedelta(days=2), today - timedelta(days=1)]
    made=[]
    for day in days:
        missing = _missing_types(user.id, day)
        if not missing:
            continue
        row = ChecklistComplianceCase.query.filter_by(driver_id=user.id, missed_date=day).first()
        if not row:
            row = ChecklistComplianceCase(driver_id=user.id, base_code=user.base_code, missed_date=day, missing_types=','.join(missing))
            db.session.add(row); db.session.flush()
        else:
            row.missing_types = ','.join(missing)
        made.append(row)
    # Dois dias seguidos com falha = aprovação obrigatória. O mais recente governa o bloqueio.
    if len(made) >= 2 and (made[-1].missed_date - made[-2].missed_date).days == 1:
        made[-1].consecutive_count = 2
        if made[-1].status in {'WAITING_JUSTIFICATION','JUSTIFIED'}:
            made[-1].status = 'WAITING_JUSTIFICATION' if not made[-1].justification else 'PENDING_APPROVAL'
    db.session.commit()
    return ChecklistComplianceCase.query.filter(
        ChecklistComplianceCase.driver_id == user.id,
        ChecklistComplianceCase.status.in_(('WAITING_JUSTIFICATION','PENDING_APPROVAL','REJECTED')),
    ).order_by(ChecklistComplianceCase.missed_date.asc()).all()


def _compliance_view():
    if current_user.role != 'DRIVER':
        return redirect(url_for('main.dashboard'))
    cases = _ensure_cases(current_user)
    return render_template('driver/checklist_compliance.html', cases=cases)


def _justify(case_id):
    row = db.session.get(ChecklistComplianceCase, case_id) or abort(404)
    if row.driver_id != current_user.id: abort(403)
    text = (request.form.get('justification') or '').strip()
    if len(text) < 8:
        flash('Informe uma justificativa mais completa.', 'danger')
        return redirect(url_for('checklist_compliance'))
    row.justification = text
    row.justified_at = utc_now()
    row.status = 'PENDING_APPROVAL' if row.consecutive_count >= 2 else 'JUSTIFIED'
    db.session.add(AuditLog(action='CHECKLIST_MISSED_JUSTIFICATION', entity_type='CHECKLIST_COMPLIANCE', entity_id=row.id, description=f'{current_user.name} justificou ausência de checklist em {row.missed_date.strftime("%d/%m/%Y")}: {text}', base_code=row.base_code, user_id=current_user.id))
    db.session.commit()
    if row.status == 'PENDING_APPROVAL':
        flash('Justificativa enviada. Como houve 2 dias consecutivos, seu acesso ficará bloqueado até a liberação do Líder/Coordenador.', 'warning')
    else:
        flash('Justificativa registrada. Acesso liberado.', 'success')
    return redirect(url_for('checklist_compliance'))


def _decide(case_id, decision):
    if not current_user.is_admin: abort(403)
    row = db.session.get(ChecklistComplianceCase, case_id) or abort(404)
    if current_user.is_base_admin and row.base_code != current_user.base_code: abort(403)
    if decision not in {'approve','reject'}: abort(400)
    row.status = 'APPROVED' if decision == 'approve' else 'REJECTED'
    row.decided_at = utc_now(); row.decided_by_id = current_user.id
    row.decision_note = (request.form.get('note') or '').strip() or None
    db.session.add(AuditLog(action='CHECKLIST_COMPLIANCE_DECISION', entity_type='CHECKLIST_COMPLIANCE', entity_id=row.id, description=f'{current_user.name} definiu {row.status} para {row.driver.name} - falta de checklist em {row.missed_date.strftime("%d/%m/%Y")}.', base_code=row.base_code, user_id=current_user.id))
    db.session.commit()
    flash('Motorista liberado.' if row.status == 'APPROVED' else 'Justificativa recusada; o motorista continua bloqueado.', 'success' if row.status == 'APPROVED' else 'warning')
    return redirect(url_for('main.admin_checklists'))


def _month_bounds(raw=None):
    today=local_today()
    raw=(raw or f'{today.year:04d}-{today.month:02d}').strip()
    try:
        y,m=map(int,raw.split('-',1)); start=date(y,m,1)
    except Exception:
        y,m=today.year,today.month; raw=f'{y:04d}-{m:02d}'; start=date(y,m,1)
    end=date(y+1,1,1) if m==12 else date(y,m+1,1)
    return raw,start,end


def _admin_checklists_current_month():
    if not current_user.is_admin: abort(403)
    raw,start,end=_month_bounds(request.args.get('month'))
    q=DailyChecklist.query.filter(DailyChecklist.is_deleted.is_(False), DailyChecklist.checklist_date>=start, DailyChecklist.checklist_date<end)
    if current_user.is_base_admin: q=q.filter(DailyChecklist.base_code==current_user.base_code)
    checklists=q.options(selectinload(DailyChecklist.driver),selectinload(DailyChecklist.vehicle)).order_by(DailyChecklist.created_at.desc()).all()
    nq=AdminNotification.query.filter(AdminNotification.created_at>=start, AdminNotification.created_at<end)
    if current_user.is_base_admin: nq=nq.filter(AdminNotification.base_code==current_user.base_code)
    notifications=nq.order_by(AdminNotification.created_at.desc()).limit(30).all()
    mq=Expense.query.filter(Expense.expense_type=='MAINTENANCE',Expense.is_deleted.is_(False),Expense.expense_date>=start,Expense.expense_date<end)
    if current_user.is_base_admin: mq=mq.filter(Expense.base_code==current_user.base_code)
    maintenance=mq.options(selectinload(Expense.vehicle),selectinload(Expense.responsible_driver),selectinload(Expense.maintenance)).order_by(Expense.expense_date.desc(),Expense.id.desc()).all()

    months_q=db.session.query(extract('year',DailyChecklist.checklist_date).label('y'),extract('month',DailyChecklist.checklist_date).label('m'),func.count(DailyChecklist.id)).filter(DailyChecklist.is_deleted.is_(False))
    if current_user.is_base_admin: months_q=months_q.filter(DailyChecklist.base_code==current_user.base_code)
    months_q=months_q.group_by('y','m').order_by(extract('year',DailyChecklist.checklist_date).desc(),extract('month',DailyChecklist.checklist_date).desc()).limit(12).all()
    archive=[]
    for y,m,count in months_q:
        iy,im=int(y),int(m); value=f'{iy:04d}-{im:02d}'
        archive.append({'value':value,'label':f'{MONTHS_PT[im-1]} {iy}','count':count,'active':value==raw})

    # Se o motorista já atingiu 2 dias consecutivos sem checklist, o admin precisa
    # enxergá-lo imediatamente para poder liberar o acesso, mesmo antes da justificativa.
    blocked_q=ChecklistComplianceCase.query.filter(
        ChecklistComplianceCase.consecutive_count >= 2,
        ChecklistComplianceCase.status == 'WAITING_JUSTIFICATION',
    )
    if current_user.is_base_admin:
        blocked_q=blocked_q.filter_by(base_code=current_user.base_code)
    waiting_blocked=blocked_q.all()
    if waiting_blocked:
        for case in waiting_blocked:
            case.status='PENDING_APPROVAL'
        db.session.commit()

    cq=ChecklistComplianceCase.query.filter(ChecklistComplianceCase.status.in_(('PENDING_APPROVAL','REJECTED')))
    if current_user.is_base_admin: cq=cq.filter_by(base_code=current_user.base_code)
    compliance_cases=cq.options(selectinload(ChecklistComplianceCase.driver)).order_by(ChecklistComplianceCase.missed_date.desc()).all()
    return render_template('admin/checklists.html', checklists=checklists, notifications=notifications, checklist_maintenance=maintenance, checklist_months=archive, selected_checklist_month=raw, selected_checklist_month_label=f'{MONTHS_PT[start.month-1]} {start.year}', compliance_cases=compliance_cases)


def init_checklist_compliance_upgrade(app):
    app.add_url_rule('/checklist-pendente', 'checklist_compliance', login_required(_compliance_view), methods=['GET'])
    app.add_url_rule('/checklist-pendente/<int:case_id>/justificar', 'checklist_compliance_justify', login_required(_justify), methods=['POST'])
    app.add_url_rule('/admin/checklist-compliance/<int:case_id>/<decision>', 'checklist_compliance_decide', login_required(_decide), methods=['POST'])
    app.view_functions['main.admin_checklists'] = login_required(_admin_checklists_current_month)

    @app.before_request
    def force_driver_compliance():
        if not current_user.is_authenticated or current_user.role != 'DRIVER': return None
        if request.endpoint in {'auth.logout','checklist_compliance','checklist_compliance_justify','static'} or (request.endpoint or '').startswith('static'):
            return None
        try:
            cases=_ensure_cases(current_user)
        except Exception:
            app.logger.exception('Falha ao validar pendência de checklist')
            return None
        if cases:
            # Falta simples: obriga justificar. Dois dias seguidos: fica bloqueado até aprovação.
            return redirect(url_for('checklist_compliance'))
        return None
