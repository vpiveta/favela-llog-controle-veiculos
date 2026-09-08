from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from flask import render_template, request, send_file
from flask_login import current_user, login_required
from sqlalchemy import extract, func
from sqlalchemy.orm import selectinload
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from pypdf import PdfReader, PdfWriter

from .models import db, Expense, DailyChecklist
from .time_utils import local_today

MONTHS_PT = ('Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro')
MOTORCYCLE_IMAGE = Path(__file__).resolve().parent / 'static' / 'img' / 'motorcycle_ref.png'


def _bounds(year, month):
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def _base_filter(q, model):
    if current_user.is_global_admin:
        base = (request.args.get('base') or 'ALL').upper()
        if base != 'ALL': q = q.filter(model.base_code == base)
        return q, base
    base = current_user.base_code
    return q.filter(model.base_code == base), base


def current_month_report():
    from .production_upgrade import _money_total, _vehicle_scope
    today = local_today(); start, end = _bounds(today.year, today.month)
    q = Expense.query.filter(Expense.asset_type == 'MOTORCYCLE', Expense.is_deleted.is_(False), Expense.expense_date >= start, Expense.expense_date < end)
    q, base_code = _base_filter(q, Expense)
    if not current_user.is_admin:
        q = q.filter(Expense.vehicle_id == current_user.vehicle.id) if current_user.vehicle else q.filter(Expense.id == -1)
    rows = q.options(selectinload(Expense.vehicle), selectinload(Expense.responsible_driver), selectinload(Expense.created_by), selectinload(Expense.maintenance), selectinload(Expense.fuel)).order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    grouped, drivers = {}, {}
    for e in rows:
        item = grouped.setdefault(e.vehicle_id, {'vehicle': e.vehicle, 'total': Decimal('0'), 'fuel': Decimal('0'), 'maintenance': Decimal('0'), 'count': 0})
        value = Decimal(e.amount); item['total'] += value; item['count'] += 1
        if e.expense_type == 'FUEL': item['fuel'] += value
        if e.expense_type == 'MAINTENANCE': item['maintenance'] += value
        driver = e.responsible_driver or e.vehicle.driver
        if driver:
            d = drivers.setdefault(driver.id, {'driver': driver, 'total': Decimal('0'), 'count': 0}); d['total'] += value; d['count'] += 1
    by_vehicle = sorted(grouped.values(), key=lambda x: x['total'], reverse=True)
    by_driver = sorted(drivers.values(), key=lambda x: x['total'], reverse=True)
    max_vehicle_total = by_vehicle[0]['total'] if by_vehicle else Decimal('1')
    vehicles = _vehicle_scope(base_code).count()
    cq = DailyChecklist.query.filter(DailyChecklist.checklist_date >= start, DailyChecklist.checklist_date < end, DailyChecklist.is_deleted.is_(False))
    if base_code != 'ALL': cq = cq.filter(DailyChecklist.base_code == base_code)
    if not current_user.is_admin: cq = cq.filter(DailyChecklist.driver_id == current_user.id)
    return render_template('reports/monthly.html', month=start.strftime('%Y-%m'), month_label=f'{MONTHS_PT[start.month-1]} {start.year}', base_code=base_code, is_global=current_user.is_global_admin, total=_money_total(rows), fuel=_money_total(rows,'FUEL'), maintenance=_money_total(rows,'MAINTENANCE'), vehicles=vehicles, checklist_count=cq.count(), by_vehicle=by_vehicle, by_driver=by_driver, rows=rows, max_vehicle_total=max_vehicle_total)


def monthly_history():
    from .routes import car_plate_photo_ids
    today = local_today(); raw = (request.args.get('month') or f'{today.year:04d}-{today.month:02d}').strip()
    try:
        year, month = map(int, raw.split('-',1)); start, end = _bounds(year, month)
    except Exception:
        year, month = today.year, today.month; start, end = _bounds(year, month); raw = f'{year:04d}-{month:02d}'
    base = Expense.query.filter(Expense.is_deleted.is_(False))
    if not current_user.is_global_admin: base = base.filter(Expense.base_code == current_user.base_code)
    if not current_user.is_admin: base = base.filter(Expense.vehicle_id == current_user.vehicle.id) if current_user.vehicle else base.filter(Expense.id == -1)
    kind = request.args.get('type')
    if kind: base = base.filter(Expense.expense_type == kind)
    month_rows = db.session.query(extract('year', Expense.expense_date).label('y'), extract('month', Expense.expense_date).label('m'), func.count(Expense.id)).filter(Expense.is_deleted.is_(False))
    if not current_user.is_global_admin: month_rows = month_rows.filter(Expense.base_code == current_user.base_code)
    if not current_user.is_admin and current_user.vehicle: month_rows = month_rows.filter(Expense.vehicle_id == current_user.vehicle.id)
    month_rows = month_rows.group_by('y','m').order_by(extract('year', Expense.expense_date).desc(), extract('month', Expense.expense_date).desc()).limit(12).all()
    history_months=[]
    for y,m,count in month_rows:
        iy,im=int(y),int(m); value=f'{iy:04d}-{im:02d}'; history_months.append({'value':value,'label':f'{MONTHS_PT[im-1]} {iy}','count':count,'active':value==raw})
    expenses = base.filter(Expense.expense_date >= start, Expense.expense_date < end).options(selectinload(Expense.vehicle), selectinload(Expense.created_by), selectinload(Expense.responsible_driver), selectinload(Expense.maintenance), selectinload(Expense.fuel)).order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    motorcycle_expenses=[e for e in expenses if e.asset_type=='MOTORCYCLE']; car_expenses=[e for e in expenses if e.asset_type=='CAR']
    motorcycle_total=sum((Decimal(e.amount) for e in motorcycle_expenses),Decimal('0')); car_total=sum((Decimal(e.amount) for e in car_expenses),Decimal('0'))
    return render_template('driver/history.html', motorcycle_expenses=motorcycle_expenses, car_expenses=car_expenses, motorcycle_total=motorcycle_total, car_total=car_total, car_plate_photo_ids=car_plate_photo_ids(car_expenses), selected_asset_type=request.args.get('asset_type','').upper(), history_pagination=None, history_months=history_months, selected_month=raw, selected_month_label=f'{MONTHS_PT[month-1]} {year}')


def _pdf_with_motorcycle(original, title, rows, filename):
    response = original(title, rows, filename)
    if not str(title).lower().startswith('checklist') or not MOTORCYCLE_IMAGE.exists():
        return response
    try:
        response.direct_passthrough = False
        pdf_bytes = response.get_data()
        overlay = BytesIO(); w, h = A4
        c = pdfcanvas.Canvas(overlay, pagesize=A4)
        c.drawImage(str(MOTORCYCLE_IMAGE), 67*mm, h-78*mm, 31*mm, 23*mm, preserveAspectRatio=True, mask='auto')
        c.save(); overlay.seek(0)
        base_reader = PdfReader(BytesIO(pdf_bytes)); overlay_reader = PdfReader(overlay)
        if base_reader.pages:
            base_reader.pages[0].merge_page(overlay_reader.pages[0])
        writer = PdfWriter()
        for page in base_reader.pages: writer.add_page(page)
        out = BytesIO(); writer.write(out); out.seek(0)
        return send_file(out, mimetype='application/pdf', as_attachment=False, download_name=filename)
    except Exception:
        return response


def init_system_v6(app):
    app.view_functions['production.monthly_report'] = login_required(current_month_report)
    app.view_functions['main.history'] = login_required(monthly_history)
    from . import enterprise19
    previous_pdf = enterprise19._pdf_response
    enterprise19._pdf_response = lambda title, rows, filename: _pdf_with_motorcycle(previous_pdf, title, rows, filename)
    @app.after_request
    def inject_v6(response):
        if response.mimetype == 'text/html':
            try:
                html=response.get_data(as_text=True)
                if 'system-v6.css' not in html and '</head>' in html: html=html.replace('</head>','<link rel="stylesheet" href="/static/css/system-v6.css"></head>',1)
                if 'system-v6.js' not in html and '</body>' in html: html=html.replace('</body>','<script src="/static/js/system-v6.js"></script></body>',1)
                response.set_data(html)
            except Exception: pass
        return response
