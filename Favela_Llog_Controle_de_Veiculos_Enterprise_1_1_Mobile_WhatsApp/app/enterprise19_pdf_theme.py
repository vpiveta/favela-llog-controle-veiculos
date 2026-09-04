import io
from pathlib import Path

from flask import send_file
from PIL import Image, ImageChops
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

TURQUOISE = colors.HexColor('#17D8DF')
TURQUOISE_DARK = colors.HexColor('#079BA2')
BLACK = colors.HexColor('#070A0B')
PANEL = colors.HexColor('#0B1012')
WHITE = colors.HexColor('#F7FAFC')
MUTED = colors.HexColor('#A8B2B7')
AMBER = colors.HexColor('#FF9D18')
GREEN = colors.HexColor('#18CF58')
RED = colors.HexColor('#FF4D57')
BORDER = colors.HexColor('#3C4A4F')

BACKGROUND_PATH = Path(__file__).resolve().parent / 'static' / 'img' / 'background.png'
_BACKGROUND_READER = None


def _teal_version(image):
    rgba = image.convert('RGBA')
    alpha = rgba.getchannel('A')
    hsv = rgba.convert('RGB').convert('HSV')
    hue, saturation, value = hsv.split()
    warm_mask = hue.point(lambda h: 255 if (h < 45 or h > 245) else 0)
    saturation_mask = saturation.point(lambda s: 255 if s > 35 else 0)
    mask = ImageChops.multiply(warm_mask, saturation_mask)
    teal_hue = Image.new('L', rgba.size, 128)
    boosted_saturation = saturation.point(lambda s: max(s, 150))
    hue = Image.composite(teal_hue, hue, mask)
    saturation = Image.composite(boosted_saturation, saturation, mask)
    result = Image.merge('HSV', (hue, saturation, value)).convert('RGBA')
    result.putalpha(alpha)
    return result


def _background_reader():
    global _BACKGROUND_READER
    if _BACKGROUND_READER is not None:
        return _BACKGROUND_READER
    if not BACKGROUND_PATH.exists():
        return None
    image = _teal_version(Image.open(BACKGROUND_PATH))
    buf = io.BytesIO()
    image.save(buf, format='PNG', optimize=True)
    buf.seek(0)
    _BACKGROUND_READER = ImageReader(buf)
    return _BACKGROUND_READER


def _draw_background(c, w, h):
    bg = _background_reader()
    if bg:
        iw, ih = bg.getSize()
        scale = max(w / float(iw), h / float(ih))
        dw, dh = iw * scale, ih * scale
        c.drawImage(bg, (w - dw) / 2, (h - dh) / 2, dw, dh, preserveAspectRatio=True, mask='auto')
    else:
        c.setFillColor(BLACK)
        c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColor(colors.Color(0, 0, 0, alpha=.50))
    c.rect(0, 0, w, h, fill=1, stroke=0)


def _panel(c, x, y, w, h, radius=3*mm):
    c.setFillColor(colors.Color(0.025, 0.035, 0.04, alpha=.90))
    c.setStrokeColor(BORDER)
    c.setLineWidth(.7)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def _txt(c, text, x, y, size=8, color=WHITE, font='Helvetica'):
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawString(x, y, str(text or '-'))


def _fit(c, text, x, y, maxw, size=8, color=WHITE, font='Helvetica'):
    text = str(text or '-')
    while size > 5.8 and c.stringWidth(text, font, size) > maxw:
        size -= .3
    _txt(c, text, x, y, size, color, font)


def _label_value(c, label, value, x, y, value_x, maxw):
    _txt(c, label.upper(), x, y, 6.4, TURQUOISE, 'Helvetica-Bold')
    _fit(c, value, value_x, y, maxw, 7.8, WHITE, 'Helvetica-Bold')


def _status_pill(c, status, x, y, w=24*mm):
    upper = str(status or '').upper()
    if 'ATEN' in upper or 'NÃO' in upper or 'NAO' in upper:
        stroke, fill = AMBER, colors.Color(0.20, 0.12, 0.01, alpha=.95)
    elif 'OK' in upper or 'BOA' in upper:
        stroke, fill = GREEN, colors.Color(0.02, 0.20, 0.08, alpha=.95)
    else:
        stroke, fill = MUTED, colors.Color(0.12, 0.14, 0.15, alpha=.95)
    c.setStrokeColor(stroke)
    c.setFillColor(fill)
    c.roundRect(x, y, w, 5.2*mm, 2.5*mm, fill=1, stroke=1)
    c.setFillColor(stroke if stroke != MUTED else WHITE)
    c.setFont('Helvetica-Bold', 6.4)
    c.drawCentredString(x + w/2, y + 1.55*mm, upper[:16])


def _parse_rows(rows):
    data = {}
    items = []
    known = {'Base','Tipo','Data','Motorista que utilizou','CNH do motorista','Responsável da moto','Responsável cadastrado','CNH do responsável','Moto','Veículo','KM','Uso temporário','Justificativa','Estado geral','Avaria','Status'}
    for label, value in rows:
        if label in known:
            data[label] = str(value or '-')
        else:
            items.append((str(label), str(value or '-')))
    return data, items


def _draw_signature(c, name, x, y, width):
    c.setFillColor(WHITE)
    c.setFont('Helvetica-Oblique', 15)
    c.drawCentredString(x + width/2, y + 8*mm, name or '-')
    c.setStrokeColor(BORDER)
    c.line(x + 8*mm, y + 6*mm, x + width - 8*mm, y + 6*mm)
    c.setFont('Helvetica', 6.2)
    c.setFillColor(MUTED)
    c.drawCentredString(x + width/2, y + 2.5*mm, name or '-')


def _draw_qr(c, payload, x, y, size=19*mm):
    qr = QrCodeWidget(payload)
    b = qr.getBounds()
    bw, bh = b[2]-b[0], b[3]-b[1]
    d = Drawing(size, size, transform=[size/bw,0,0,size/bh,0,0])
    d.add(qr)
    renderPDF.draw(d, c, x, y)


def _checklist_pdf(title, rows, filename):
    data, items = _parse_rows(rows)
    buf = io.BytesIO()
    w, h = A4
    c = pdfcanvas.Canvas(buf, pagesize=A4)
    _draw_background(c, w, h)

    margin = 12*mm
    content_w = w - 2*margin

    # Cabeçalho igual à referência: marca à esquerda, título ao centro, metadados à direita.
    _txt(c, 'FAVELA', margin, h-23*mm, 20, WHITE, 'Helvetica-Bold')
    _txt(c, 'LLOG', margin+2*mm, h-31*mm, 15, TURQUOISE, 'Helvetica-Bold')
    _txt(c, 'CHECKLIST DIÁRIO', 72*mm, h-22*mm, 18, WHITE, 'Helvetica-Bold')
    _txt(c, 'RETIRADA / DEVOLUÇÃO', 73*mm, h-31*mm, 10, TURQUOISE, 'Helvetica-Bold')
    _panel(c, w-64*mm, h-38*mm, 52*mm, 27*mm, 2*mm)
    _label_value(c, 'DATA', data.get('Data','-'), w-60*mm, h-19*mm, w-43*mm, 29*mm)
    _label_value(c, 'BASE', data.get('Base','-'), w-60*mm, h-27*mm, w-43*mm, 29*mm)
    _label_value(c, 'TIPO', data.get('Tipo','-'), w-60*mm, h-35*mm, w-43*mm, 29*mm)

    # Veículo / responsáveis
    top_y = h-82*mm
    left_w = 91*mm
    gap = 3*mm
    right_w = content_w-left_w-gap
    _panel(c, margin, top_y, left_w, 39*mm)
    _txt(c, 'VEÍCULO', margin+5*mm, top_y+32*mm, 9, TURQUOISE, 'Helvetica-Bold')
    moto = data.get('Moto') or data.get('Veículo') or '-'
    plate = moto.split(' - ')[-1] if ' - ' in moto else moto.split('·')[-1].strip()
    model = moto.rsplit(' - ',1)[0] if ' - ' in moto else moto
    _label_value(c, 'PLACA', plate, margin+5*mm, top_y+23*mm, margin+30*mm, 50*mm)
    _label_value(c, 'MODELO', model, margin+5*mm, top_y+15*mm, margin+30*mm, 52*mm)
    _label_value(c, 'KM ATUAL', data.get('KM','-'), margin+5*mm, top_y+7*mm, margin+30*mm, 45*mm)

    _panel(c, margin+left_w+gap, top_y, right_w, 39*mm)
    rx = margin+left_w+gap+5*mm
    _txt(c, 'RESPONSÁVEL OFICIAL', rx, top_y+32*mm, 8.5, TURQUOISE, 'Helvetica-Bold')
    owner = data.get('Responsável da moto') or data.get('Responsável cadastrado') or '-'
    _label_value(c, 'NOME', owner, rx, top_y+24*mm, rx+21*mm, right_w-30*mm)
    _label_value(c, 'CNH', data.get('CNH do responsável','-'), rx, top_y+17*mm, rx+21*mm, right_w-30*mm)
    _txt(c, 'UTILIZADO POR', rx, top_y+10*mm, 8.5, TURQUOISE, 'Helvetica-Bold')
    _fit(c, data.get('Motorista que utilizou','-'), rx+21*mm, top_y+3.8*mm, right_w-30*mm, 7.5, WHITE, 'Helvetica-Bold')
    _txt(c, 'CNH', rx, top_y+3.8*mm, 6.4, TURQUOISE, 'Helvetica-Bold')

    # Tabela de itens
    table_y = 89*mm
    table_h = top_y-table_y-4*mm
    _panel(c, margin, table_y, content_w, table_h)
    _txt(c, 'CHECKLIST DE ITENS', margin+5*mm, table_y+table_h-8*mm, 9, TURQUOISE, 'Helvetica-Bold')
    header_y = table_y+table_h-15*mm
    c.setFillColor(colors.Color(.12,.14,.15,alpha=.95)); c.rect(margin+3*mm, header_y-1.5*mm, content_w-6*mm, 7*mm, fill=1, stroke=0)
    _txt(c,'ITEM',margin+7*mm,header_y+0.5*mm,6.5,WHITE,'Helvetica-Bold')
    _txt(c,'STATUS',margin+71*mm,header_y+0.5*mm,6.5,WHITE,'Helvetica-Bold')
    _txt(c,'OBSERVAÇÃO / MOTIVO',margin+104*mm,header_y+0.5*mm,6.5,WHITE,'Helvetica-Bold')
    _txt(c,'FOTO',margin+171*mm,header_y+0.5*mm,6.5,WHITE,'Helvetica-Bold')
    row_h = 7*mm
    y = header_y-6.5*mm
    max_rows = min(len(items), 11)
    attention = 0
    for label, value in items[:max_rows]:
        c.setStrokeColor(colors.HexColor('#30383C')); c.line(margin+4*mm,y-1*mm,w-margin-4*mm,y-1*mm)
        _fit(c,label.upper(),margin+7*mm,y+1*mm,58*mm,6.7,WHITE,'Helvetica-Bold')
        _status_pill(c,value,margin+69*mm,y-1*mm,27*mm)
        obs = '---'
        if 'ATEN' in value.upper():
            attention += 1
            obs = value.split('-',1)[1].strip() if '-' in value else 'Item requer atenção.'
        _fit(c,obs,margin+103*mm,y+1*mm,62*mm,6.2,WHITE)
        _txt(c,'✓' if 'OK' in value.upper() else '—',margin+177*mm,y+1*mm,10,GREEN if 'OK' in value.upper() else MUTED,'Helvetica-Bold')
        y -= row_h

    # Atenção
    att_y = table_y+4*mm
    c.setStrokeColor(AMBER if attention else GREEN); c.setLineWidth(.8)
    c.roundRect(margin+4*mm, att_y, content_w-8*mm, 10*mm, 2*mm, fill=0, stroke=1)
    _txt(c,'⚠ ITENS COM ATENÇÃO:' if attention else '✓ CHECKLIST SEM PENDÊNCIAS',margin+8*mm,att_y+5.8*mm,6.7,AMBER if attention else GREEN,'Helvetica-Bold')
    _txt(c,f'{attention} item(ns) com atenção que necessitam acompanhamento.' if attention else 'Todos os itens conferidos estão OK.',margin+8*mm,att_y+2.5*mm,6,WHITE)

    # Observação geral
    obs_y = 66*mm
    _panel(c, margin, obs_y, content_w, 19*mm)
    _txt(c,'OBSERVAÇÃO GERAL',margin+5*mm,obs_y+12*mm,8.5,TURQUOISE,'Helvetica-Bold')
    note = data.get('Avaria','Não informada')
    if data.get('Justificativa') and data.get('Justificativa') != '-':
        note = f"{note} · {data.get('Justificativa')}"
    _fit(c,note,margin+5*mm,obs_y+5*mm,content_w-10*mm,6.8,WHITE)

    # Assinaturas
    sig_y = 34*mm
    _panel(c, margin, sig_y, content_w, 28*mm)
    _txt(c,'ASSINATURAS',margin+5*mm,sig_y+21*mm,8.5,TURQUOISE,'Helvetica-Bold')
    half = (content_w-8*mm)/2
    _txt(c,'UTILIZADO POR',margin+7*mm,sig_y+16*mm,6.4,WHITE,'Helvetica-Bold')
    _txt(c,'RESPONSÁVEL OFICIAL',margin+half+7*mm,sig_y+16*mm,6.4,WHITE,'Helvetica-Bold')
    _draw_signature(c,data.get('Motorista que utilizou','-'),margin+4*mm,sig_y,half)
    _draw_signature(c,owner,margin+half+4*mm,sig_y,half)

    # QR/código
    _panel(c, 70*mm, 10*mm, 70*mm, 20*mm, 2*mm)
    _draw_qr(c, filename, 73*mm, 11.5*mm, 16*mm)
    _txt(c,'CÓDIGO DO CHECKLIST',93*mm,22*mm,6,TURQUOISE,'Helvetica-Bold')
    code = Path(filename).stem.upper().replace('CHECKLIST-','CHK-')
    _fit(c,code,93*mm,16*mm,42*mm,8.5,TURQUOISE,'Helvetica-Bold')
    _txt(c,'Favela Llog - Controle de Veículos',70*mm,5.5*mm,7,TURQUOISE,'Helvetica-Bold')

    c.showPage(); c.save(); buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=False, download_name=filename)


def _generic_pdf(title, rows, filename):
    # Mantém o mesmo tema para abastecimentos e manutenções.
    buf = io.BytesIO(); w,h=A4
    c = pdfcanvas.Canvas(buf,pagesize=A4); _draw_background(c,w,h)
    _txt(c,'FAVELA LLOG',15*mm,h-24*mm,18,TURQUOISE,'Helvetica-Bold')
    _txt(c,str(title).upper(),15*mm,h-36*mm,15,WHITE,'Helvetica-Bold')
    y=h-50*mm
    for label,value in rows:
        if y<25*mm:
            c.showPage(); _draw_background(c,w,h); y=h-25*mm
        _panel(c,15*mm,y-10*mm,w-30*mm,9*mm,1.5*mm)
        _txt(c,str(label).upper(),20*mm,y-6*mm,6.5,TURQUOISE,'Helvetica-Bold')
        _fit(c,value,70*mm,y-6*mm,w-90*mm,7.2,WHITE)
        y-=11*mm
    c.save(); buf.seek(0)
    return send_file(buf,mimetype='application/pdf',as_attachment=False,download_name=filename)


def themed_pdf_response(title, rows, filename):
    if str(title).lower().startswith('checklist'):
        return _checklist_pdf(title, rows, filename)
    return _generic_pdf(title, rows, filename)


def init_pdf_theme(app):
    from . import enterprise19
    enterprise19._pdf_response = themed_pdf_response
