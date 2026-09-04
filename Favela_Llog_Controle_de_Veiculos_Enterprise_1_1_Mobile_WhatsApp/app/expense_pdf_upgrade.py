import io
from pathlib import Path

from flask import abort, current_app, send_file
from flask_login import current_user, login_required
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas

from .models import db, Expense, StoredFile
from .storage import download_bytes
from . import enterprise19_pdf_theme as theme

WHITE = colors.HexColor('#F7FAFC')
MUTED = colors.HexColor('#A8B2B7')
TEAL = colors.HexColor('#17D8DF')
BORDER = colors.HexColor('#3C4A4F')
GREEN = colors.HexColor('#18CF58')
AMBER = colors.HexColor('#FF9D18')


def _txt(c, text, x, y, size=8, color=WHITE, font='Helvetica'):
    c.setFillColor(color); c.setFont(font, size); c.drawString(x, y, str(text or '-'))


def _fit(c, text, x, y, maxw, size=8, color=WHITE, font='Helvetica-Bold'):
    text = str(text or '-')
    while size > 5.4 and c.stringWidth(text, font, size) > maxw:
        size -= .25
    _txt(c, text, x, y, size, color, font)


def _panel(c, x, y, w, h, radius=3*mm):
    c.setFillColor(colors.Color(0.02, 0.03, 0.035, alpha=.93))
    c.setStrokeColor(BORDER); c.setLineWidth(.7)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def _label_value(c, label, value, x, y, value_x, maxw):
    _txt(c, label.upper(), x, y, 6.2, TEAL, 'Helvetica-Bold')
    _fit(c, value, value_x, y, maxw, 7.5, WHITE, 'Helvetica-Bold')


def _money(v):
    return f'R$ {float(v or 0):.2f}'.replace('.', ',')


def _receipt_row(expense):
    return StoredFile.query.filter(
        StoredFile.entity_id == expense.id,
        StoredFile.entity_type.in_(('EXPENSE', 'MOTORCYCLE_EXPENSE')),
        StoredFile.category.in_(('RECEIPT', 'MOTORCYCLE_RECEIPT')),
    ).order_by(StoredFile.id.desc()).first()


def _receipt_bytes(expense):
    row = _receipt_row(expense)
    if row:
        try:
            if row.is_in_storage:
                data, mime = download_bytes(row.storage_bucket, row.storage_path)
                return data, mime or row.mime_type
            return row.content, row.mime_type
        except Exception:
            pass
    try:
        legacy = Path(current_app.config['UPLOAD_FOLDER']) / (expense.receipt_path or '')
        if legacy.is_file():
            return legacy.read_bytes(), None
    except Exception:
        pass
    return None, None


def _draw_receipt(c, raw, mime, x, y, w, h):
    if not raw:
        return False, 'Comprovante disponível no sistema.'
    if (mime or '').lower().startswith('application/pdf') or raw[:4] == b'%PDF':
        return False, 'A nota foi enviada em PDF e permanece disponível no sistema.'
    try:
        im = Image.open(io.BytesIO(raw)).convert('RGB')
        iw, ih = im.size
        scale = min(w / iw, h / ih)
        nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
        im = im.resize((nw, nh))
        buf = io.BytesIO(); im.save(buf, 'JPEG', quality=80); buf.seek(0)
        px = x + (w - nw) / 2; py = y + (h - nh) / 2
        c.drawImage(ImageReader(buf), px, py, nw, nh, preserveAspectRatio=True, mask='auto')
        return True, None
    except Exception:
        return False, 'Não foi possível incorporar a imagem; o comprovante continua salvo no sistema.'


def expense_pdf_v2(expense_id):
    e = db.session.get(Expense, expense_id) or abort(404)
    if not current_user.is_admin and e.created_by_id != current_user.id and e.responsible_driver_id != current_user.id:
        abort(403)

    kind = 'ABASTECIMENTO' if e.expense_type == 'FUEL' else 'MANUTENÇÃO'
    buf = io.BytesIO(); w, h = A4; c = pdfcanvas.Canvas(buf, pagesize=A4)
    theme._draw_background(c, w, h)
    margin = 12*mm; content = w - 2*margin

    # Deixa a arte Favela Llog respirar no canto esquerdo.
    title_x = 70*mm
    c.setFillColor(colors.Color(0,0,0,alpha=.46))
    c.roundRect(title_x-5*mm, h-39*mm, 78*mm, 29*mm, 3*mm, fill=1, stroke=0)
    _txt(c, kind, title_x, h-23*mm, 19, WHITE, 'Helvetica-Bold')
    _txt(c, 'CONTROLE DE VEÍCULOS', title_x, h-31*mm, 8.5, TEAL, 'Helvetica-Bold')
    c.setStrokeColor(TEAL); c.setLineWidth(1.5); c.line(title_x, h-35*mm, title_x+58*mm, h-35*mm)

    _panel(c, w-61*mm, h-39*mm, 49*mm, 29*mm, 2*mm)
    _label_value(c, 'DATA', e.expense_date.strftime('%d/%m/%Y'), w-57*mm, h-19*mm, w-39*mm, 25*mm)
    _label_value(c, 'BASE', e.base_code, w-57*mm, h-27*mm, w-39*mm, 25*mm)
    _label_value(c, 'TIPO', 'Abastecimento' if e.expense_type=='FUEL' else 'Manutenção', w-57*mm, h-35*mm, w-39*mm, 25*mm)

    # Identificação principal.
    top_y = h-84*mm
    _panel(c, margin, top_y, content, 39*mm)
    _txt(c, 'DADOS DO LANÇAMENTO', margin+5*mm, top_y+31*mm, 9, TEAL, 'Helvetica-Bold')
    left = margin+5*mm; mid = margin+96*mm
    vehicle = f'{e.vehicle.brand} {e.vehicle.model} · {e.vehicle.plate}'
    driver = e.responsible_driver.name if e.responsible_driver else (e.vehicle.driver.name if e.vehicle.driver else 'Sem motorista cadastrado')
    _label_value(c, 'VEÍCULO', vehicle, left, top_y+22*mm, left+27*mm, 60*mm)
    _label_value(c, 'KM', f'{e.odometer or 0} km', left, top_y+14*mm, left+27*mm, 60*mm)
    _label_value(c, 'MOTORISTA', driver, left, top_y+6*mm, left+27*mm, 60*mm)
    _label_value(c, 'LANÇADO POR', e.created_by.name, mid, top_y+22*mm, mid+32*mm, 48*mm)
    _label_value(c, 'VALOR', _money(e.amount), mid, top_y+14*mm, mid+32*mm, 48*mm)
    _label_value(c, 'STATUS', (e.maintenance.status if e.maintenance else 'REGISTRADO'), mid, top_y+6*mm, mid+32*mm, 48*mm)

    # Detalhes do gasto.
    detail_y = 151*mm
    _panel(c, margin, detail_y, content, 42*mm)
    _txt(c, 'DETALHES', margin+5*mm, detail_y+34*mm, 9, TEAL, 'Helvetica-Bold')
    y = detail_y+25*mm
    if e.fuel:
        details = [
            ('COMBUSTÍVEL', e.fuel.fuel_type or 'Gasolina'),
            ('LITROS', str(e.fuel.liters or '-')),
            ('POSTO', e.fuel.station or '-'),
        ]
    else:
        details = [
            ('SERVIÇO REALIZADO', e.maintenance.description if e.maintenance else '-'),
            ('OFICINA', e.maintenance.workshop if e.maintenance and e.maintenance.workshop else '-'),
            ('TROCA DE ÓLEO', 'Sim' if e.maintenance and e.maintenance.is_oil_change else 'Não'),
        ]
        if e.maintenance and e.maintenance.is_oil_change and e.maintenance.oil_amount:
            details.append(('VALOR DO ÓLEO', _money(e.maintenance.oil_amount)))
    for label, value in details:
        _label_value(c, label, value, margin+6*mm, y, margin+52*mm, content-60*mm)
        y -= 7.5*mm
    if e.notes:
        _fit(c, f'OBSERVAÇÃO: {e.notes}', margin+6*mm, detail_y+4*mm, content-12*mm, 6.4, MUTED, 'Helvetica')

    # Nota/comprovante.
    receipt_y = 67*mm
    _panel(c, margin, receipt_y, content, 78*mm)
    _txt(c, 'FOTO DA NOTA / COMPROVANTE', margin+5*mm, receipt_y+70*mm, 9, TEAL, 'Helvetica-Bold')
    raw, mime = _receipt_bytes(e)
    ok, message = _draw_receipt(c, raw, mime, margin+8*mm, receipt_y+7*mm, content-16*mm, 58*mm)
    if not ok:
        c.setStrokeColor(BORDER); c.rect(margin+8*mm, receipt_y+7*mm, content-16*mm, 58*mm, fill=0, stroke=1)
        _fit(c, message, margin+14*mm, receipt_y+34*mm, content-28*mm, 7.2, MUTED, 'Helvetica-Bold')

    _txt(c, f'Favela Llog · {kind.title()} · {e.vehicle.plate}', margin, 12*mm, 6.2, TEAL, 'Helvetica-Bold')
    _txt(c, f'Registro #{e.id}', w-45*mm, 12*mm, 5.8, MUTED)

    c.showPage(); c.save(); buf.seek(0)
    filename = f'{"abastecimento" if e.expense_type=="FUEL" else "manutencao"}-{e.vehicle.plate}-{e.id}.pdf'
    return send_file(buf, mimetype='application/pdf', as_attachment=False, download_name=filename)


def init_expense_pdf_upgrade(app):
    app.view_functions['enterprise19.expense_pdf'] = login_required(expense_pdf_v2)
