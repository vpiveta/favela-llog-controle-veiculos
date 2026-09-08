import io
import re
from pathlib import Path
from flask import send_file
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
from . import enterprise19_pdf_theme as theme

WHITE = colors.HexColor('#F7FAFC')
MUTED = colors.HexColor('#A8B2B7')
TEAL = colors.HexColor('#17D8DF')
AMBER = colors.HexColor('#FF9D18')
GREEN = colors.HexColor('#18CF58')
RED = colors.HexColor('#FF4D57')
BORDER = colors.HexColor('#46565C')
DARK = colors.HexColor('#080C0E')
LOGO_PATH = Path(__file__).resolve().parent / 'static' / 'img' / 'logo.png'


def _txt(c, text, x, y, size=8, color=WHITE, font='Helvetica'):
    c.setFillColor(color); c.setFont(font, size); c.drawString(x, y, str(text or '-'))


def _fit(c, text, x, y, maxw, size=8, color=WHITE, font='Helvetica-Bold'):
    text = str(text or '-')
    while size > 5 and c.stringWidth(text, font, size) > maxw: size -= .25
    _txt(c, text, x, y, size, color, font)


def _panel(c, x, y, w, h, radius=2.4*mm):
    c.setFillColor(colors.Color(.015,.022,.025,alpha=.91)); c.setStrokeColor(BORDER); c.setLineWidth(.7); c.roundRect(x,y,w,h,radius,fill=1,stroke=1)


def _label(c, label, value, x, y, vx, maxw):
    _txt(c,label.upper(),x,y,6.1,TEAL,'Helvetica-Bold'); _fit(c,value,vx,y,maxw,7.2,WHITE,'Helvetica-Bold')


def _parse(rows):
    known={'Base','Tipo','Data','Motorista que utilizou','CNH do motorista','Responsável da moto','Responsável cadastrado','CNH do responsável','Moto','Veículo','KM','Uso temporário','Justificativa','Estado geral','Avaria','Status'}
    data,items={},[]
    for a,b in rows:
        if a in known:data[a]=str(b or '-')
        else:items.append((str(a),str(b or '-')))
    return data,items


def _status(c,value,x,y,w=24*mm):
    u=str(value or '').upper(); ok='OK' in u or 'BOA' in u
    neutral='NÃO POSSUI' in u or 'NAO POSSUI' in u
    stroke=MUTED if neutral else (GREEN if ok else AMBER)
    fill=colors.Color(.10,.11,.12,alpha=.95) if neutral else (colors.Color(.02,.20,.08,alpha=.95) if ok else colors.Color(.20,.12,.01,alpha=.95))
    c.setStrokeColor(stroke); c.setFillColor(fill); c.roundRect(x,y,w,5*mm,2.4*mm,fill=1,stroke=1); c.setFillColor(WHITE if neutral else stroke); c.setFont('Helvetica-Bold',6.0)
    c.drawCentredString(x+w/2,y+1.45*mm,'NÃO POSSUI' if neutral else ('OK' if ok else 'ATENÇÃO'))


def _draw_qr(c,payload,x,y,size=19*mm):
    qr=QrCodeWidget(payload); b=qr.getBounds(); bw,bh=b[2]-b[0],b[3]-b[1]; d=Drawing(size,size,transform=[size/bw,0,0,size/bh,0,0]); d.add(qr); renderPDF.draw(d,c,x,y)


def _draw_logo(c,x,y,w=43*mm,h=28*mm):
    try:
        if LOGO_PATH.exists(): c.drawImage(ImageReader(str(LOGO_PATH)),x,y,w,h,preserveAspectRatio=True,mask='auto')
    except Exception: pass


def _draw_photo(c, raw, x, y, w, h):
    if not raw:return False
    try:
        im=Image.open(io.BytesIO(raw)).convert('RGB'); im.thumbnail((700,700)); buf=io.BytesIO(); im.save(buf,'JPEG',quality=68,optimize=True); buf.seek(0); c.drawImage(ImageReader(buf),x,y,w,h,preserveAspectRatio=True,anchor='c',mask='auto'); return True
    except Exception:return False


def checklist_pdf(title,rows,filename):
    data,items=_parse(rows); w,h=A4; buf=io.BytesIO(); c=pdfcanvas.Canvas(buf,pagesize=A4); theme._draw_background(c,w,h)
    margin=11*mm; content=w-2*margin
    # Header
    _draw_logo(c,margin,h-40*mm,49*mm,30*mm)
    _txt(c,'CHECKLIST DIÁRIO',72*mm,h-20*mm,18,WHITE,'Helvetica-Bold'); _txt(c,'RETIRADA / DEVOLUÇÃO',73*mm,h-29*mm,10,TEAL,'Helvetica-Bold')
    _panel(c,w-62*mm,h-39*mm,51*mm,28*mm,2*mm); _label(c,'DATA / HORA',data.get('Data','-'),w-58*mm,h-18*mm,w-38*mm,25*mm); _label(c,'BASE',data.get('Base','-'),w-58*mm,h-26*mm,w-38*mm,25*mm); _label(c,'TIPO',data.get('Tipo','-'),w-58*mm,h-34*mm,w-38*mm,25*mm)
    # Vehicle and people
    top=h-83*mm; lw=91*mm; gap=3*mm; rw=content-lw-gap; _panel(c,margin,top,lw,39*mm); _panel(c,margin+lw+gap,top,rw,39*mm)
    _txt(c,'VEÍCULO',margin+5*mm,top+32*mm,8.5,TEAL,'Helvetica-Bold'); moto=data.get('Moto') or data.get('Veículo') or '-'; plate=moto.split(' - ')[-1] if ' - ' in moto else moto.split('·')[-1].strip(); model=moto.rsplit(' - ',1)[0] if ' - ' in moto else moto
    _label(c,'PLACA',plate,margin+5*mm,top+23*mm,margin+29*mm,54*mm); _label(c,'MODELO',model,margin+5*mm,top+15*mm,margin+29*mm,54*mm); _label(c,'KM ATUAL',data.get('KM','-'),margin+5*mm,top+7*mm,margin+29*mm,45*mm)
    rx=margin+lw+gap+5*mm; owner=data.get('Responsável da moto') or data.get('Responsável cadastrado') or '-'; _txt(c,'RESPONSÁVEL OFICIAL',rx,top+32*mm,8.2,TEAL,'Helvetica-Bold'); _label(c,'NOME',owner,rx,top+24*mm,rx+20*mm,rw-28*mm); _label(c,'CNH',data.get('CNH do responsável','-'),rx,top+17*mm,rx+20*mm,rw-28*mm); _txt(c,'UTILIZADO POR',rx,top+10*mm,8.2,TEAL,'Helvetica-Bold'); _label(c,'NOME',data.get('Motorista que utilizou','-'),rx,top+3*mm,rx+20*mm,rw-28*mm)
    # Table
    table_y=91*mm; table_h=top-table_y-4*mm; _panel(c,margin,table_y,content,table_h); _txt(c,'CHECKLIST DE ITENS',margin+5*mm,table_y+table_h-8*mm,8.8,TEAL,'Helvetica-Bold')
    hy=table_y+table_h-15*mm; c.setFillColor(colors.Color(.12,.14,.15,alpha=.95)); c.rect(margin+3*mm,hy-1.6*mm,content-6*mm,7*mm,fill=1,stroke=0); _txt(c,'ITEM',margin+7*mm,hy+.5*mm,6.2,WHITE,'Helvetica-Bold'); _txt(c,'STATUS',margin+70*mm,hy+.5*mm,6.2,WHITE,'Helvetica-Bold'); _txt(c,'OBSERVAÇÃO / MOTIVO',margin+103*mm,hy+.5*mm,6.2,WHITE,'Helvetica-Bold'); _txt(c,'FOTO',margin+173*mm,hy+.5*mm,6.2,WHITE,'Helvetica-Bold')
    m=re.search(r'-(\d+)\.pdf$',filename or ''); checklist_id=int(m.group(1)) if m else None; photos=[]
    if checklist_id: photos=StoredFile.query.filter_by(entity_type='CHECKLIST',entity_id=checklist_id).order_by(StoredFile.id).all()
    y=hy-6.5*mm; attention=0
    for idx,(label,value) in enumerate(items[:10]):
        c.setStrokeColor(colors.HexColor('#30383C')); c.line(margin+4*mm,y-1*mm,w-margin-4*mm,y-1*mm); _fit(c,label.upper(),margin+7*mm,y+1*mm,57*mm,6.4,WHITE,'Helvetica-Bold'); _status(c,value,margin+68*mm,y-1*mm,27*mm)
        u=value.upper(); obs='---'
        if 'ATEN' in u: attention+=1; obs=value.split('-',1)[1].strip() if '-' in value else 'Item requer atenção.'
        elif 'NÃO POSSUI' in u or 'NAO POSSUI' in u: obs=value.split('-',1)[1].strip() if '-' in value else 'Não possui.'
        _fit(c,obs,margin+102*mm,y+1*mm,65*mm,5.8,WHITE,'Helvetica')
        raw=None
        if idx < len(photos) and photos[idx].content: raw=photos[idx].content
        if raw and _draw_photo(c,raw,margin+173*mm,y-2.2*mm,14*mm,6.5*mm): pass
        else: _txt(c,'✓' if 'OK' in u else '—',margin+179*mm,y+.5*mm,9,GREEN if 'OK' in u else MUTED,'Helvetica-Bold')
        y-=6.6*mm
    att_y=table_y+3.5*mm; c.setStrokeColor(AMBER if attention else GREEN); c.roundRect(margin+4*mm,att_y,content-8*mm,10*mm,2*mm,fill=0,stroke=1); _txt(c,'⚠  ITENS COM ATENÇÃO:' if attention else '✓  CHECKLIST SEM PENDÊNCIAS',margin+8*mm,att_y+5.8*mm,6.6,AMBER if attention else GREEN,'Helvetica-Bold'); _txt(c,f'{attention} item(ns) com atenção que necessitam acompanhamento.' if attention else 'Todos os itens conferidos estão OK.',margin+8*mm,att_y+2.4*mm,5.9,WHITE)
    # Observation
    obs_y=67*mm; _panel(c,margin,obs_y,content,20*mm); _txt(c,'OBSERVAÇÃO GERAL',margin+5*mm,obs_y+13*mm,8.5,TEAL,'Helvetica-Bold'); note=data.get('Avaria','Sem mais avarias aparentes.'); just=data.get('Justificativa','-'); note=note if just in ('-','') else f'{note} · {just}'; _fit(c,note,margin+5*mm,obs_y+5*mm,content-10*mm,6.5,WHITE,'Helvetica')
    # Signatures
    sig_y=34*mm; _panel(c,margin,sig_y,content,28*mm); _txt(c,'ASSINATURAS',margin+5*mm,sig_y+21*mm,8.5,TEAL,'Helvetica-Bold'); half=(content-8*mm)/2
    for idx,(lab,name,cnh) in enumerate((('UTILIZADO POR',data.get('Motorista que utilizou','-'),data.get('CNH do motorista','-')),('RESPONSÁVEL OFICIAL',owner,data.get('CNH do responsável','-')))):
        x=margin+4*mm+idx*half; _txt(c,lab,x+4*mm,sig_y+16*mm,6.0,WHITE,'Helvetica-Bold'); c.setFont('Helvetica-Oblique',13); c.setFillColor(WHITE); c.drawCentredString(x+half/2,sig_y+9.5*mm,name); c.setStrokeColor(BORDER); c.line(x+8*mm,sig_y+7*mm,x+half-8*mm,sig_y+7*mm); c.setFont('Helvetica',5.5); c.setFillColor(MUTED); c.drawCentredString(x+half/2,sig_y+3.5*mm,name); c.drawCentredString(x+half/2,sig_y+1.2*mm,f'CNH: {cnh}')
    # QR footer
    qr_y=10*mm; _panel(c,69*mm,qr_y,72*mm,20*mm,2*mm); payload=filename or 'checklist'; _txt(c,'Consulte este checklist',72*mm,qr_y+12*mm,5.4,WHITE); _txt(c,'escaneando o QR Code.',72*mm,qr_y+8.5*mm,5.4,WHITE); _draw_qr(c,payload,100*mm,qr_y+1.5*mm,17*mm); code=(re.sub(r'[^0-9]','',filename or '')[-8:] or '00000000'); _txt(c,'CÓDIGO DO CHECKLIST',120*mm,qr_y+12*mm,5.3,MUTED,'Helvetica-Bold'); _txt(c,f'CHK-{code}',120*mm,qr_y+6*mm,9,TEAL,'Helvetica-Bold')
    c.setFont('Helvetica-Bold',6.5); c.setFillColor(TEAL); c.drawCentredString(w/2,5.6*mm,'Favela Llog - Controle de Veículos'); c.setFont('Helvetica',5.6); c.setFillColor(WHITE); c.drawCentredString(w/2,3.2*mm,'Sonhos, Disciplina & Fé')
    c.showPage(); c.save(); buf.seek(0); return send_file(buf,mimetype='application/pdf',as_attachment=False,download_name=filename)


def init_checklist_pdf_upgrade(app):
    from . import enterprise19
    original=enterprise19._pdf_response
    def wrapper(title,rows,filename):
        if str(title).lower().startswith('checklist'):
            try:return checklist_pdf(title,rows,filename)
            except Exception:
                app.logger.exception('Falha ao gerar PDF visual do checklist; usando PDF de segurança'); return original(title,rows,filename)
        return original(title,rows,filename)
    enterprise19._pdf_response=wrapper
