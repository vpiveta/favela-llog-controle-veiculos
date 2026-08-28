import io
from flask import send_file
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

TURQUOISE = colors.HexColor('#16D4D8')
TURQUOISE_DARK = colors.HexColor('#079BA2')
BLACK = colors.HexColor('#070A0B')
PANEL = colors.HexColor('#101719')
PANEL_2 = colors.HexColor('#162125')
WHITE = colors.HexColor('#F7FAFC')
MUTED = colors.HexColor('#B7C5C9')


def _favela_background(canvas, doc):
    """Fundo inspirado no padrão oficial enviado: preto texturizado + bordas turquesa."""
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(BLACK)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)

    # Faixas/pinceladas turquesa irregulares nas bordas.
    canvas.setFillColor(TURQUOISE)
    canvas.setFillAlpha(0.92)
    canvas.setStrokeColor(TURQUOISE)
    canvas.setLineWidth(5)
    canvas.line(0, h-5*mm, 33*mm, h-22*mm)
    canvas.line(0, h-15*mm, 18*mm, h-50*mm)
    canvas.line(w, h-2*mm, w-30*mm, h-24*mm)
    canvas.line(w, h-18*mm, w-16*mm, h-60*mm)
    canvas.line(0, 3*mm, 32*mm, 26*mm)
    canvas.line(0, 15*mm, 18*mm, 48*mm)
    canvas.line(w, 3*mm, w-34*mm, 25*mm)
    canvas.line(w, 17*mm, w-18*mm, 52*mm)

    # Marca d'água lateral, lembrando a coroa/grafite do padrão.
    canvas.setFillAlpha(0.10)
    canvas.setFont('Helvetica-Bold', 72)
    canvas.drawRightString(w-8*mm, h-78*mm, 'M')
    canvas.setFillAlpha(1)

    # Cabeçalho Favela Llog.
    canvas.setFillColor(WHITE)
    canvas.setFont('Helvetica-BoldOblique', 21)
    canvas.drawString(22*mm, h-24*mm, 'FAVELA')
    canvas.setFillColor(TURQUOISE)
    canvas.setFont('Helvetica-BoldOblique', 19)
    canvas.drawString(31*mm, h-32*mm, 'LLOG')
    canvas.setStrokeColor(WHITE)
    canvas.setLineWidth(1.2)
    canvas.line(22*mm, h-35*mm, 61*mm, h-35*mm)

    # Área central escura para leitura dos dados.
    canvas.setFillColor(PANEL)
    canvas.setFillAlpha(0.94)
    canvas.roundRect(18*mm, 28*mm, w-36*mm, h-72*mm, 5*mm, fill=1, stroke=0)
    canvas.setFillAlpha(1)
    canvas.setStrokeColor(TURQUOISE_DARK)
    canvas.setLineWidth(0.8)
    canvas.roundRect(18*mm, 28*mm, w-36*mm, h-72*mm, 5*mm, fill=0, stroke=1)

    canvas.setFillColor(MUTED)
    canvas.setFont('Helvetica', 7.2)
    canvas.drawCentredString(w/2, 15*mm, f'FAVELA LLOG • CONTROLE DE VEÍCULOS • Página {doc.page}')
    canvas.restoreState()


def themed_pdf_response(title, rows, filename):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=25*mm, leftMargin=25*mm,
        topMargin=49*mm, bottomMargin=35*mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'FavelaTitle', parent=styles['Title'], alignment=TA_CENTER,
        textColor=WHITE, fontName='Helvetica-Bold', fontSize=17, leading=20,
        spaceAfter=2*mm,
    )
    subtitle_style = ParagraphStyle(
        'FavelaSubtitle', parent=styles['Normal'], alignment=TA_CENTER,
        textColor=TURQUOISE, fontName='Helvetica-Bold', fontSize=8.5,
        leading=11, spaceAfter=5*mm,
    )
    label_style = ParagraphStyle(
        'FavelaLabel', parent=styles['BodyText'], textColor=TURQUOISE,
        fontName='Helvetica-Bold', fontSize=8.2, leading=10.5,
    )
    value_style = ParagraphStyle(
        'FavelaValue', parent=styles['BodyText'], textColor=WHITE,
        fontName='Helvetica', fontSize=8.2, leading=10.5,
    )
    foot_style = ParagraphStyle(
        'FavelaFoot', parent=styles['Normal'], alignment=TA_CENTER,
        textColor=MUTED, fontSize=7.2, leading=9,
    )

    story = [
        Paragraph(title.upper(), title_style),
        Paragraph('REGISTRO OPERACIONAL • FAVELA LLOG', subtitle_style),
    ]
    data = []
    for label, value in rows:
        label = str(label).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        value = str(value if value not in (None, '') else '-').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br/>')
        data.append([Paragraph(label, label_style), Paragraph(value, value_style)])

    table = Table(data, colWidths=[47*mm, 105*mm], hAlign='CENTER')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), PANEL_2),
        ('BOX', (0,0), (-1,-1), 0.75, TURQUOISE_DARK),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.HexColor('#2A4146')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 7),
        ('RIGHTPADDING', (0,0), (-1,-1), 7),
        ('TOPPADDING', (0,0), (-1,-1), 5.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5.5),
    ]))
    story.append(table)
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph('Documento gerado automaticamente pelo sistema Favela Llog.', foot_style))
    doc.build(story, onFirstPage=_favela_background, onLaterPages=_favela_background)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=False, download_name=filename)


def init_pdf_theme(app):
    # Os endpoints existentes continuam iguais; trocamos apenas o motor visual do PDF.
    from . import enterprise19
    enterprise19._pdf_response = themed_pdf_response
