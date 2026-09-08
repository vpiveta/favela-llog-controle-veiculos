import io
import re
from pathlib import Path

from flask import send_file, url_for
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

from .models import StoredFile

WHITE = colors.HexColor('#F7FAFC')
MUTED = colors.HexColor('#A8B2B7')
TEAL = colors.HexColor('#00E6E6')
TEAL_DARK = colors.HexColor('#073238')
GREEN = colors.HexColor('#00E67A')
AMBER = colors.HexColor('#FFAE28')
RED = colors.HexColor('#FF4D57')
BORDER = colors.HexColor('#42545B')
DARK = colors.HexColor('#050A0D')
PANEL = colors.HexColor('#071116')
PANEL_2 = colors.HexColor('#0B161B')
HEADER = colors.HexColor('#22292D')
LOGO_PATH = Path(__file__).resolve().parent / 'static' / 'img' / 'logo.png'
MOTORCYCLE_PATH = Path(__file__).resolve().parent / 'static' / 'img' / 'motorcycle_ref.png'


def _txt(c, text, x, y, size=8, color=WHITE, font='Helvetica'):
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawString(x, y, str(text or '-'))


def _fit(c, text, x, y, maxw, size=8, color=WHITE, font='Helvetica-Bold'):
    text = str(text or '-')
    while size > 4.8 and c.stringWidth(text, font, size) > maxw:
        size -= .25
    _txt(c, text, x, y, size, color, font)


def _panel(c, x, y, w, h, radius=2.2 * mm, stroke=BORDER, fill=PANEL):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(.65)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def _label(c, label, value, x, y, vx, maxw):
    _txt(c, label.upper(), x, y, 5.8, TEAL, 'Helvetica-Bold')
    _fit(c, value, vx, y, maxw, 6.8, WHITE, 'Helvetica-Bold')


def _parse(rows):
    known = {
        'Base', 'Tipo', 'Data', 'Motorista que utilizou', 'CNH do motorista',
        'Responsável da moto', 'Responsável cadastrado', 'CNH do responsável',
        'Moto', 'Veículo', 'KM', 'Uso temporário', 'Justificativa',
        'Estado geral', 'Avaria', 'Status', 'Telefone', 'Telefone do responsável',
        'CPF do motorista', 'CPF do responsável', 'Cor', 'Ano'
    }
    data, items = {}, []
    for a, b in rows:
        if a in known:
            data[a] = str(b or '-')
        else:
            items.append((str(a), str(b or '-')))
    return data, items


def _status(c, value, x, y, w=24 * mm):
    u = str(value or '').upper()
    ok = 'OK' in u or 'BOA' in u
    neutral = 'NÃO POSSUI' in u or 'NAO POSSUI' in u
    stroke = MUTED if neutral else (GREEN if ok else AMBER)
    fill = colors.HexColor('#1A1F22') if neutral else (colors.HexColor('#07351D') if ok else colors.HexColor('#3B2705'))
    c.setStrokeColor(stroke)
    c.setFillColor(fill)
    c.roundRect(x, y, w, 5.1 * mm, 2.5 * mm, fill=1, stroke=1)
    c.setFillColor(WHITE if neutral else stroke)
    c.setFont('Helvetica-Bold', 5.8)
    c.drawCentredString(x + w / 2, y + 1.45 * mm, 'NÃO POSSUI' if neutral else ('OK' if ok else 'ATENÇÃO'))


def _draw_qr(c, payload, x, y, size=22 * mm):
    qr = QrCodeWidget(payload)
    b = qr.getBounds()
    bw, bh = b[2] - b[0], b[3] - b[1]
    d = Drawing(size, size, transform=[size / bw, 0, 0, size / bh, 0, 0])
    d.add(qr)
    c.setFillColor(colors.white)
    c.roundRect(x - 1.4 * mm, y - 1.4 * mm, size + 2.8 * mm, size + 2.8 * mm, 1.2 * mm, fill=1, stroke=0)
    renderPDF.draw(d, c, x, y)


def _draw_image(c, path, x, y, w, h, opacity=1):
    try:
        if path.exists():
            c.saveState()
            if opacity < 1 and hasattr(c, 'setFillAlpha'):
                c.setFillAlpha(opacity)
            c.drawImage(ImageReader(str(path)), x, y, w, h, preserveAspectRatio=True, anchor='c', mask='auto')
            c.restoreState()
            return True
    except Exception:
        pass
    return False


def _draw_photo(c, raw, x, y, w, h):
    if not raw:
        return False
    try:
        im = Image.open(io.BytesIO(raw)).convert('RGB')
        im.thumbnail((700, 700))
        buf = io.BytesIO()
        im.save(buf, 'JPEG', quality=68, optimize=True)
        buf.seek(0)
        c.drawImage(ImageReader(buf), x, y, w, h, preserveAspectRatio=True, anchor='c', mask='auto')
        return True
    except Exception:
        return False


def _background(c, w, h):
    c.setFillColor(DARK)
    c.rect(0, 0, w, h, fill=1, stroke=0)

    # Textura discreta para reproduzir o fundo preto do modelo sem duplicar o logo.
    c.saveState()
    if hasattr(c, 'setFillAlpha'):
        c.setFillAlpha(.05)
    c.setFillColor(colors.HexColor('#758087'))
    for i in range(0, 28):
        yy = 8 * mm + i * 10.2 * mm
        c.rect(0, yy, w, .18 * mm, fill=1, stroke=0)
    c.restoreState()

    # Faixas ciano apenas nas bordas, deixando o centro limpo.
    c.saveState()
    if hasattr(c, 'setFillAlpha'):
        c.setFillAlpha(.92)
    c.setFillColor(TEAL)
    c.setStrokeColor(TEAL)
    c.setLineWidth(1.2)
    c.line(1.5 * mm, 18 * mm, 1.5 * mm, h - 15 * mm)
    c.line(w - 1.5 * mm, 17 * mm, w - 1.5 * mm, h - 15 * mm)
    for yy, ww in ((24, 8), (50, 5), (82, 7), (118, 5), (166, 8), (224, 6), (270, 9)):
        c.rect(0, yy * mm, ww * mm, 2.4 * mm, fill=1, stroke=0)
        c.rect(w - ww * mm, (yy + 5) * mm, ww * mm, 2.1 * mm, fill=1, stroke=0)
    c.restoreState()


def _plate_from_moto(moto):
    moto = str(moto or '-').strip()
    if ' - ' in moto:
        return moto.split(' - ')[-1].strip()
    if '·' in moto:
        return moto.split('·')[-1].strip()
    match = re.search(r'\b[A-Z]{3}[0-9A-Z][0-9A-Z][0-9]{2}\b', moto.upper())
    return match.group(0) if match else moto


def checklist_pdf(title, rows, filename):
    data, items = _parse(rows)
    w, h = A4
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=A4)
    _background(c, w, h)

    margin = 10 * mm
    content = w - 2 * margin

    # CABEÇALHO — um único logo, sem sobreposição.
    _draw_image(c, LOGO_PATH, margin + 1 * mm, h - 43 * mm, 50 * mm, 31 * mm)
    _txt(c, 'CONTROLE DE VEÍCULOS', margin + 9 * mm, h - 42 * mm, 5.4, MUTED, 'Helvetica-Bold')
    _txt(c, 'CHECKLIST DIÁRIO', 71 * mm, h - 21 * mm, 18.2, WHITE, 'Helvetica-Bold')
    _txt(c, 'RETIRADA / DEVOLUÇÃO', 73 * mm, h - 30 * mm, 10.2, TEAL, 'Helvetica-Bold')
    c.setStrokeColor(TEAL)
    c.setLineWidth(.7)
    c.line(73 * mm, h - 33 * mm, 139 * mm, h - 33 * mm)
    _txt(c, 'SEGURANÇA HOJE, MAIS ENTREGAS AMANHÃ', 76 * mm, h - 37 * mm, 4.8, MUTED, 'Helvetica-Bold')

    _panel(c, w - 61 * mm, h - 43 * mm, 50 * mm, 32 * mm, 2 * mm)
    _label(c, 'DATA / HORA', data.get('Data', '-'), w - 57 * mm, h - 20 * mm, w - 38 * mm, 24 * mm)
    _label(c, 'BASE', data.get('Base', '-'), w - 57 * mm, h - 29 * mm, w - 38 * mm, 24 * mm)
    _label(c, 'TIPO', data.get('Tipo', '-'), w - 57 * mm, h - 38 * mm, w - 38 * mm, 24 * mm)

    moto = data.get('Moto') or data.get('Veículo') or '-'
    plate = _plate_from_moto(moto)
    model = moto.rsplit(' - ', 1)[0] if ' - ' in moto else moto.replace(plate, '').replace('·', '').strip(' -') or '-'

    # LINHA VEÍCULO + QR + RESPONSÁVEL
    top = h - 91 * mm
    left_w = 94 * mm
    qr_w = 39 * mm
    gap = 2.2 * mm
    right_w = content - left_w - qr_w - 2 * gap

    _panel(c, margin, top, left_w, 44 * mm)
    _panel(c, margin + left_w + gap, top, qr_w, 44 * mm, stroke=TEAL_DARK)
    _panel(c, margin + left_w + qr_w + 2 * gap, top, right_w, 44 * mm)

    _txt(c, 'VEÍCULO', margin + 5 * mm, top + 36 * mm, 8.5, TEAL, 'Helvetica-Bold')
    _label(c, 'PLACA', plate, margin + 5 * mm, top + 27 * mm, margin + 28 * mm, 34 * mm)
    _label(c, 'MODELO', model, margin + 5 * mm, top + 19 * mm, margin + 28 * mm, 34 * mm)
    if data.get('Cor'):
        _label(c, 'COR', data.get('Cor'), margin + 5 * mm, top + 11 * mm, margin + 28 * mm, 34 * mm)
    _label(c, 'KM ATUAL', data.get('KM', '-'), margin + 5 * mm, top + 3.5 * mm, margin + 28 * mm, 34 * mm)
    _draw_image(c, MOTORCYCLE_PATH, margin + 53 * mm, top + 4 * mm, 36 * mm, 31 * mm)

    qx = margin + left_w + gap
    _txt(c, 'QR CODE DO VEÍCULO', qx + 4 * mm, top + 36 * mm, 7.2, TEAL, 'Helvetica-Bold')
    try:
        qr_payload = url_for('production.search', q=plate, _external=True)
    except Exception:
        qr_payload = f'https://favela-llog-controle-veiculos.onrender.com/buscar?q={plate}'
    _draw_qr(c, qr_payload, qx + 8.5 * mm, top + 11 * mm, 21 * mm)
    c.setFont('Helvetica-Bold', 6.3)
    c.setFillColor(TEAL)
    c.drawCentredString(qx + qr_w / 2, top + 5 * mm, plate)

    rx = margin + left_w + qr_w + 2 * gap + 4 * mm
    owner = data.get('Responsável da moto') or data.get('Responsável cadastrado') or '-'
    _txt(c, 'RESPONSÁVEL OFICIAL', rx, top + 36 * mm, 7.6, TEAL, 'Helvetica-Bold')
    _label(c, 'NOME', owner, rx, top + 28 * mm, rx + 17 * mm, right_w - 24 * mm)
    phone = data.get('Telefone do responsável') or data.get('Telefone') or '-'
    _label(c, 'TELEFONE', phone, rx, top + 20.5 * mm, rx + 17 * mm, right_w - 24 * mm)
    _txt(c, 'UTILIZADO POR', rx, top + 13 * mm, 7.6, TEAL, 'Helvetica-Bold')
    _label(c, 'NOME', data.get('Motorista que utilizou', '-'), rx, top + 5 * mm, rx + 17 * mm, right_w - 24 * mm)

    # CHECKLIST
    table_y = 92 * mm
    table_h = top - table_y - 4 * mm
    _panel(c, margin, table_y, content, table_h)
    _txt(c, 'CHECKLIST DE ITENS', margin + 5 * mm, table_y + table_h - 8 * mm, 8.8, TEAL, 'Helvetica-Bold')
    hy = table_y + table_h - 15 * mm
    c.setFillColor(HEADER)
    c.roundRect(margin + 3 * mm, hy - 1.8 * mm, content - 6 * mm, 7.2 * mm, 1.1 * mm, fill=1, stroke=0)
    _txt(c, 'ITEM', margin + 7 * mm, hy + .5 * mm, 6.1, WHITE, 'Helvetica-Bold')
    _txt(c, 'STATUS', margin + 72 * mm, hy + .5 * mm, 6.1, WHITE, 'Helvetica-Bold')
    _txt(c, 'OBSERVAÇÃO / MOTIVO', margin + 108 * mm, hy + .5 * mm, 6.1, WHITE, 'Helvetica-Bold')
    _txt(c, 'FOTO', margin + 177 * mm, hy + .5 * mm, 6.1, WHITE, 'Helvetica-Bold')

    m = re.search(r'-(\d+)\.pdf$', filename or '')
    checklist_id = int(m.group(1)) if m else None
    photos = []
    if checklist_id:
        photos = StoredFile.query.filter_by(entity_type='CHECKLIST', entity_id=checklist_id).order_by(StoredFile.id).all()

    y = hy - 6.2 * mm
    attention = 0
    display_items = items[:10]
    for idx, (label, value) in enumerate(display_items):
        c.setStrokeColor(colors.HexColor('#30383C'))
        c.line(margin + 4 * mm, y - 1 * mm, w - margin - 4 * mm, y - 1 * mm)
        _fit(c, label.upper(), margin + 7 * mm, y + 1 * mm, 58 * mm, 6.3, WHITE, 'Helvetica-Bold')
        _status(c, value, margin + 67 * mm, y - 1.1 * mm, 28 * mm)
        u = value.upper()
        obs = '---'
        if 'ATEN' in u:
            attention += 1
            obs = value.split('-', 1)[1].strip() if '-' in value else 'Item requer atenção.'
        elif 'NÃO POSSUI' in u or 'NAO POSSUI' in u:
            obs = value.split('-', 1)[1].strip() if '-' in value else 'Não possui.'
        _fit(c, obs, margin + 104 * mm, y + 1 * mm, 66 * mm, 5.6, WHITE, 'Helvetica')

        raw = photos[idx].content if idx < len(photos) and photos[idx].content else None
        if raw and _draw_photo(c, raw, margin + 175 * mm, y - 2.2 * mm, 13 * mm, 6.4 * mm):
            pass
        else:
            c.setStrokeColor(GREEN if 'OK' in u else MUTED)
            c.circle(margin + 181 * mm, y + .9 * mm, 2.2 * mm, fill=0, stroke=1)
            _txt(c, 'OK' if 'OK' in u else '-', margin + 179.4 * mm, y - .1 * mm, 4.3, GREEN if 'OK' in u else MUTED, 'Helvetica-Bold')
        y -= 6.45 * mm

    att_y = table_y + 3.6 * mm
    c.setStrokeColor(AMBER if attention else GREEN)
    c.roundRect(margin + 4 * mm, att_y, content - 8 * mm, 10 * mm, 2 * mm, fill=0, stroke=1)
    _txt(c, 'ITENS COM ATENÇÃO' if attention else 'CHECKLIST SEM PENDÊNCIAS', margin + 9 * mm, att_y + 5.8 * mm, 6.6, AMBER if attention else GREEN, 'Helvetica-Bold')
    _txt(c, f'{attention} item(ns) necessitam acompanhamento.' if attention else 'Todos os itens conferidos estão OK.', margin + 9 * mm, att_y + 2.4 * mm, 5.9, WHITE)

    # OBSERVAÇÃO GERAL
    obs_y = 66 * mm
    _panel(c, margin, obs_y, content, 20 * mm)
    _txt(c, 'OBSERVAÇÃO GERAL', margin + 5 * mm, obs_y + 13 * mm, 8.4, TEAL, 'Helvetica-Bold')
    note = data.get('Avaria', 'Moto entregue em boas condições. Sem mais avarias aparentes.')
    just = data.get('Justificativa', '-')
    if just not in ('-', ''):
        note = f'{note} · {just}'
    _fit(c, note, margin + 5 * mm, obs_y + 5 * mm, content - 10 * mm, 6.4, WHITE, 'Helvetica')

    # ASSINATURAS
    sig_y = 31 * mm
    _panel(c, margin, sig_y, content, 30 * mm)
    _txt(c, 'ASSINATURAS', margin + 5 * mm, sig_y + 23 * mm, 8.5, TEAL, 'Helvetica-Bold')
    half = content / 2
    signature_data = (
        ('UTILIZADO POR', data.get('Motorista que utilizou', '-'), data.get('CPF do motorista') or data.get('CNH do motorista', '-')),
        ('RESPONSÁVEL OFICIAL', owner, data.get('CPF do responsável') or data.get('CNH do responsável', '-')),
    )
    for idx, (lab, name, doc) in enumerate(signature_data):
        x = margin + idx * half
        if idx:
            c.setStrokeColor(BORDER)
            c.line(x, sig_y + 4 * mm, x, sig_y + 22 * mm)
        c.setFont('Helvetica-Bold', 5.9)
        c.setFillColor(WHITE)
        c.drawCentredString(x + half / 2, sig_y + 18 * mm, lab)
        c.setFont('Helvetica-Oblique', 13)
        c.drawCentredString(x + half / 2, sig_y + 10.5 * mm, name)
        c.setStrokeColor(colors.HexColor('#AAB7BC'))
        c.line(x + 14 * mm, sig_y + 8 * mm, x + half - 14 * mm, sig_y + 8 * mm)
        c.setFont('Helvetica', 5.4)
        c.setFillColor(MUTED)
        c.drawCentredString(x + half / 2, sig_y + 4.5 * mm, name)
        if doc and doc != '-':
            c.drawCentredString(x + half / 2, sig_y + 2 * mm, f'Documento: {doc}')

    # RODAPÉ
    _txt(c, 'Favela Llog - Controle de Veículos', 66 * mm, 14 * mm, 7.0, TEAL, 'Helvetica-Bold')
    _txt(c, 'Sonhos, Disciplina & Fé', 83 * mm, 9.5 * mm, 6.2, WHITE)
    _txt(c, f'QR do veículo: {plate}', margin, 5.3 * mm, 4.8, MUTED)

    c.showPage()
    c.save()
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=False, download_name=filename)


def init_checklist_pdf_upgrade(app):
    from . import enterprise19
    original = enterprise19._pdf_response

    def wrapper(title, rows, filename):
        if str(title).lower().startswith('checklist'):
            try:
                return checklist_pdf(title, rows, filename)
            except Exception:
                app.logger.exception('Falha ao gerar PDF visual do checklist; usando PDF de segurança')
                return original(title, rows, filename)
        return original(title, rows, filename)

    enterprise19._pdf_response = wrapper
