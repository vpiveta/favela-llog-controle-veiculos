import io
from pathlib import Path

from flask import send_file
from PIL import Image, ImageChops
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle

TURQUOISE = colors.HexColor('#17D8DF')
TURQUOISE_DARK = colors.HexColor('#079BA2')
BLACK = colors.HexColor('#070A0B')
PANEL = colors.HexColor('#0B1012')
WHITE = colors.HexColor('#F7FAFC')
AMBER = colors.HexColor('#FFB020')

# A arte original do sistema tem resolução suficiente para A4. A versão
# anterior do PDF usava uma miniatura comprimida e ainda a esticava.
BACKGROUND_PATH = Path(__file__).resolve().parent / 'static' / 'img' / 'background.png'
_BACKGROUND_READER = None


def _teal_version(image):
    """Converte a identidade quente da arte antiga para turquesa sem deformá-la.

    A seleção é feita no espaço HSV: somente pixels realmente coloridos em tons
    quentes são alterados. Preto, cinza, branco, textura, prédios e lettering
    permanecem intactos. O brilho original é preservado, mantendo profundidade.
    """
    rgba = image.convert('RGBA')
    alpha = rgba.getchannel('A')
    hsv = rgba.convert('RGB').convert('HSV')
    hue, saturation, value = hsv.split()

    # Tons quentes da arte antiga (vermelho/laranja/amarelo) + saturação mínima.
    warm_mask = hue.point(lambda h: 255 if (h < 45 or h > 245) else 0)
    saturation_mask = saturation.point(lambda s: 255 if s > 35 else 0)
    mask = ImageChops.multiply(warm_mask, saturation_mask)

    # Cyan/turquesa em HSV. Mantemos o canal value para conservar luz/sombra.
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


def _draw_background_proportional(canvas, bg, page_width, page_height):
    """Preenche o A4 mantendo rigorosamente a proporção da arte."""
    img_width, img_height = bg.getSize()
    scale = max(page_width / float(img_width), page_height / float(img_height))
    draw_width = img_width * scale
    draw_height = img_height * scale
    x = (page_width - draw_width) / 2.0
    y = (page_height - draw_height) / 2.0
    canvas.drawImage(
        bg,
        x,
        y,
        width=draw_width,
        height=draw_height,
        preserveAspectRatio=True,
        mask='auto',
    )


def _favela_background(canvas, doc):
    """Fundo Favela Llog em alta resolução, sem alongar ou achatar a imagem."""
    w, h = A4
    canvas.saveState()
    bg = _background_reader()
    if bg:
        _draw_background_proportional(canvas, bg, w, h)
    else:
        canvas.setFillColor(BLACK)
        canvas.rect(0, 0, w, h, fill=1, stroke=0)

    # Área de leitura somente no centro; logo, coroa, favela e parede ficam livres.
    canvas.setFillColor(PANEL)
    canvas.setFillAlpha(0.76)
    canvas.roundRect(20 * mm, 67 * mm, w - 40 * mm, h - 122 * mm, 3.5 * mm, fill=1, stroke=0)
    canvas.setFillAlpha(1)
    canvas.setStrokeColor(TURQUOISE_DARK)
    canvas.setLineWidth(0.65)
    canvas.roundRect(20 * mm, 67 * mm, w - 40 * mm, h - 122 * mm, 3.5 * mm, fill=0, stroke=1)
    canvas.restoreState()


def themed_pdf_response(title, rows, filename):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=26 * mm,
        leftMargin=26 * mm,
        topMargin=58 * mm,
        bottomMargin=72 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'FavelaTitle', parent=styles['Heading1'],
        fontName='Helvetica-Bold', fontSize=14.5, leading=17,
        textColor=WHITE, alignment=TA_CENTER, spaceAfter=1.2 * mm,
    )
    subtitle_style = ParagraphStyle(
        'FavelaSubtitle', parent=styles['BodyText'],
        fontName='Helvetica-Bold', fontSize=7.2, leading=9,
        textColor=TURQUOISE, alignment=TA_CENTER, spaceAfter=3 * mm,
    )
    label_style = ParagraphStyle(
        'FavelaLabel', parent=styles['BodyText'],
        fontName='Helvetica-Bold', fontSize=7.0, leading=8.2,
        textColor=TURQUOISE,
    )
    value_style = ParagraphStyle(
        'FavelaValue', parent=styles['BodyText'],
        fontName='Helvetica', fontSize=7.1, leading=8.2,
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
        style = attention_style if ('ATENÇÃO' in value_text.upper() or 'VENCIDA' in value_text.upper()) else value_style
        data.append([Paragraph(label_text, label_style), Paragraph(value_text, style)])

    table = Table(data, colWidths=[47 * mm, 106 * mm], hAlign='CENTER', repeatRows=0)
    commands = [
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [
            colors.Color(0.03, 0.05, 0.055, alpha=0.66),
            colors.Color(0.05, 0.075, 0.08, alpha=0.66),
        ]),
        ('GRID', (0, 0), (-1, -1), 0.30, colors.HexColor('#2B5054')),
        ('BOX', (0, 0), (-1, -1), 0.65, TURQUOISE_DARK),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 3.2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.2),
    ]

    for idx, (label, value) in enumerate(rows):
        text = f'{label} {value}'.upper()
        if label in (
            'Base', 'Tipo', 'Data', 'Veículo', 'Moto',
            'Motorista que utilizou', 'Motorista responsável',
            'CNH do motorista', 'CNH do responsável',
        ):
            commands.append(('LINEBELOW', (0, idx), (-1, idx), 0.55, TURQUOISE_DARK))
        if 'ATENÇÃO' in text or 'VENCIDA' in text:
            commands.append(('BOX', (0, idx), (-1, idx), 0.8, AMBER))

    table.setStyle(TableStyle(commands))
    story.append(table)

    doc.build(story, onFirstPage=_favela_background, onLaterPages=_favela_background)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=False, download_name=filename)


def init_pdf_theme(app):
    from . import enterprise19
    enterprise19._pdf_response = themed_pdf_response
