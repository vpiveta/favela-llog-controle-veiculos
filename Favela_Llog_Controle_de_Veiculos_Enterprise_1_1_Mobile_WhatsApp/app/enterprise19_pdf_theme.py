import io
from pathlib import Path

from flask import send_file
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

TURQUOISE = colors.HexColor('#17D8DF')
TURQUOISE_DARK = colors.HexColor('#079BA2')
BLACK = colors.HexColor('#070A0B')
PANEL = colors.HexColor('#0B1012')
PANEL_ALT = colors.HexColor('#11191C')
WHITE = colors.HexColor('#F7FAFC')
MUTED = colors.HexColor('#B7C5C9')
AMBER = colors.HexColor('#FFB020')
BACKGROUND_PATH = Path(__file__).resolve().parent / 'static' / 'img' / 'pdf_background_favela.jpg'


def _favela_background(canvas, doc):
    """Usa a arte oficial enviada como fundo integral de todas as páginas."""
    w, h = A4
    canvas.saveState()
    if BACKGROUND_PATH.exists():
        canvas.drawImage(
            str(BACKGROUND_PATH), 0, 0, width=w, height=h,
            preserveAspectRatio=False, mask='auto'
        )
    else:
        canvas.setFillColor(BLACK)
        canvas.rect(0, 0, w, h, fill=1, stroke=0)

    # A imagem já contém logo, favela, coroa e pinceladas. Apenas criamos uma
    # camada de leitura sobre a área central, sem cobrir a identidade visual.
    canvas.setFillColor(PANEL)
    canvas.setFillAlpha(0.86)
    canvas.roundRect(18*mm, 26*mm, w-36*mm, h-79*mm, 4*mm, fill=1, stroke=0)
    canvas.setFillAlpha(1)
    canvas.setStrokeColor(TURQUOISE_DARK)
    canvas.setLineWidth(0.8)
    canvas.roundRect(18*mm, 26*mm, w-36*mm, h-79*mm, 4*mm, fill=0, stroke=1)

    canvas.setFillColor(MUTED)
    canvas.setFont('Helvetica', 7)
    canvas.drawCentredString(w/2, 14*mm, f'FAVELA LLOG - CONTROLE DE VEÍCULOS - Página {doc.page}')
    canvas.restoreState()


def themed_pdf_response(title, rows, filename):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=24*mm, leftMargin=24*mm,
        topMargin=52*mm, bottomMargin=33*mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'FavelaTitle', parent=styles['Heading1'],
        fontName='Helvetica-Bold', fontSize=17, leading=20,
        textColor=WHITE, alignment=TA_CENTER, spaceAfter=2*mm,
    )
    subtitle_style = ParagraphStyle(
        'FavelaSubtitle', parent=styles['BodyText'],
        fontName='Helvetica-Bold', fontSize=8.5, leading=11,
        textColor=TURQUOISE, alignment=TA_CENTER, spaceAfter=6*mm,
    )
    label_style = ParagraphStyle(
        'FavelaLabel', parent=styles['BodyText'],
        fontName='Helvetica-Bold', fontSize=8.4, leading=10.5,
        textColor=TURQUOISE,
    )
    value_style = ParagraphStyle(
        'FavelaValue', parent=styles['BodyText'],
        fontName='Helvetica', fontSize=8.5, leading=10.5,
        textColor=WHITE,
    )
    attention_style = ParagraphStyle(
        'FavelaAttention', parent=value_style,
        textColor=AMBER, fontName='Helvetica-Bold',
    )

    story = [
        Paragraph(str(title).upper(), title_style),
        Paragraph('CONTROLE DE VEÍCULOS', subtitle_style),
    ]

    data = []
    for label, value in rows:
        label_text = str(label or '-')
        value_text = str(value or '-').replace('\n', '<br/>')
        value_paragraph_style = attention_style if ('ATENÇÃO' in value_text.upper() or 'VENCIDA' in value_text.upper()) else value_style
        data.append([
            Paragraph(label_text, label_style),
            Paragraph(value_text, value_paragraph_style),
        ])

    table = Table(data, colWidths=[50*mm, 111*mm], hAlign='CENTER')
    commands = [
        ('BACKGROUND', (0,0), (-1,-1), colors.Color(0.035,0.055,0.06, alpha=0.76)),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.Color(0.035,0.055,0.06, alpha=0.78), colors.Color(0.055,0.085,0.095, alpha=0.78)]),
        ('GRID', (0,0), (-1,-1), 0.35, colors.HexColor('#304B50')),
        ('BOX', (0,0), (-1,-1), 0.8, TURQUOISE_DARK),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 7),
        ('RIGHTPADDING', (0,0), (-1,-1), 7),
        ('TOPPADDING', (0,0), (-1,-1), 5.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5.5),
    ]

    # Destaque visual para os blocos mais importantes do documento.
    for idx, (label, value) in enumerate(rows):
        text = f'{label} {value}'.upper()
        if label in ('Base', 'Tipo', 'Data', 'Veículo', 'Moto', 'Motorista que utilizou', 'Motorista responsável', 'CNH do motorista', 'CNH do responsável'):
            commands.append(('LINEBELOW', (0,idx), (-1,idx), 0.65, TURQUOISE_DARK))
        if 'ATENÇÃO' in text or 'VENCIDA' in text:
            commands.append(('BOX', (0,idx), (-1,idx), 0.8, AMBER))

    table.setStyle(TableStyle(commands))
    story.append(table)
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph('SONHOS, DISCIPLINA & FÉ', ParagraphStyle(
        'FavelaFooter', parent=styles['BodyText'],
        fontName='Helvetica-Bold', fontSize=7.8,
        textColor=TURQUOISE, alignment=TA_CENTER,
    )))

    doc.build(story, onFirstPage=_favela_background, onLaterPages=_favela_background)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=False, download_name=filename)


def init_pdf_theme(app):
    # O enterprise19_wait é registrado antes deste módulo e aponta os endpoints
    # para funções próprias com CNH. Substituímos somente o motor visual usado por elas.
    from . import enterprise19
    enterprise19._pdf_response = themed_pdf_response
