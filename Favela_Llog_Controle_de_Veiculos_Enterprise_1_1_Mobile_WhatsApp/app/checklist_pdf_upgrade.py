import io
import re
from flask import send_file
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas

from .models import StoredFile
from .storage import download_bytes
from . import enterprise19_pdf_theme as theme

WHITE = colors.HexColor('#F7FAFC')
MUTED = colors.HexColor('#A8B2B7')
TEAL = colors.HexColor('#17D8DF')
AMBER = colors.HexColor('#FF9D18')
GREEN = colors.HexColor('#18CF58')
BORDER = colors.HexColor('#3C4A4F')


def _txt(c, text, x, y, size=8, color=WHITE, font='Helvetica'):
    c.setFillColor(color); c.setFont(font, size); c.drawString(x, y, str(text or '-'))


def _fit(c, text, x, y, maxw, size=8, color=WHITE, font='Helvetica-Bold'):
    text = str(text or '-')
    while size > 5.5 and c.stringWidth(text, font, size) > maxw: size -= .25
    _txt(c, text, x, y, size, color, font)


def _panel(c, x, y, w, h, radius=3*mm):
    c.setFillColor(colors.Color(0.02,0.03,0.035,alpha=.92)); c.setStrokeColor(BORDER); c.setLineWidth(.7)
    c.roundRect(x,y,w,h,radius,fill=1,stroke=1)


def _label_value(c, label, value, x, y, vx, maxw):
    _txt(c,label.upper(),x,y,6.2,TEAL,'Helvetica-Bold'); _fit(c,value,vx,y,maxw,7.5,WHITE,'Helvetica-Bold')


def _parse(rows):
    known={'Base','Tipo','Data','Motorista que utilizou','CNH do motorista','Responsável da moto','Responsável cadastrado','CNH do responsável','Moto','Veículo','KM','Uso temporário','Justificativa','Estado geral','Avaria','Status'}
    data={}; items=[]
    for a,b in rows:
        (data.__setitem__(a,str(b or '-')) if a in known else items.append((str(a),str(b or '-'))))
    return data,items


def _photo_bytes(row):
    try:
        if row.is_in_storage:
            data,_=download_bytes(row.storage_bucket,row.storage_path); return data
        return row.content
    except Exception:
        return None


def _draw_photo(c, raw, x, y, w, h):
    if not raw: return False
    try:
        im=Image.open(io.BytesIO(raw)).convert('RGB')
        iw,ih=im.size; scale=max(w/iw,h/ih); nw,nh=int(iw*scale),int(ih*scale)
        im=im.resize((nw,nh)); left=max(0,(nw-int(w))/2); top=max(0,(nh-int(h))/2)
        im=im.crop((left,top,left+int(w),top+int(h)))
        buf=io.BytesIO(); im.save(buf,'JPEG',quality=82); buf.seek(0)
        c.drawImage(ImageReader(buf),x,y,w,h,preserveAspectRatio=False,mask='auto'); return True
    except Exception:
        return False


def _status(c, value, x, y):
    u=value.upper(); ok='OK' in u
    stroke=GREEN if ok else AMBER; fill=colors.Color(.02,.20,.08,alpha=.95) if ok else colors.Color(.20,.12,.01,alpha=.95)
    c.setStrokeColor(stroke); c.setFillColor(fill); c.roundRect(x,y,25*mm,5.2*mm,2.4*mm,fill=1,stroke=1)
    c.setFillColor(stroke); c.setFont('Helvetica-Bold',6.2); c.drawCentredString(x+12.5*mm,y+1.55*mm,('OK' if ok else 'ATENÇÃO'))


def checklist_pdf(title, rows, filename):
    data,items=_parse(rows); w,h=A4; buf=io.BytesIO(); c=pdfcanvas.Canvas(buf,pagesize=A4)
    theme._draw_background(c,w,h)
    margin=12*mm; content=w-2*margin

    # Reserva o canto superior esquerdo para a arte/logo do fundo.
    title_x=69*mm
    c.setFillColor(colors.Color(0,0,0,alpha=.46)); c.roundRect(title_x-5*mm,h-38*mm,76*mm,28*mm,3*mm,fill=1,stroke=0)
    _txt(c,'CHECKLIST',title_x,h-22*mm,19,WHITE,'Helvetica-Bold')
    _txt(c,'DIÁRIO',title_x+1*mm,h-30*mm,15,TEAL,'Helvetica-Bold')
    _txt(c,'RETIRADA  /  DEVOLUÇÃO',title_x,h-35*mm,7.8,WHITE,'Helvetica-Bold')
    c.setStrokeColor(TEAL); c.setLineWidth(1.5); c.line(title_x,h-37*mm,title_x+58*mm,h-37*mm)

    _panel(c,w-61*mm,h-39*mm,49*mm,29*mm,2*mm)
    _label_value(c,'DATA',data.get('Data','-'),w-57*mm,h-19*mm,w-39*mm,25*mm)
    _label_value(c,'BASE',data.get('Base','-'),w-57*mm,h-27*mm,w-39*mm,25*mm)
    _label_value(c,'TIPO',data.get('Tipo','-'),w-57*mm,h-35*mm,w-39*mm,25*mm)

    top_y=h-83*mm; left_w=91*mm; gap=3*mm; right_w=content-left_w-gap
    _panel(c,margin,top_y,left_w,38*mm); _panel(c,margin+left_w+gap,top_y,right_w,38*mm)
    _txt(c,'VEÍCULO',margin+5*mm,top_y+31*mm,8.8,TEAL,'Helvetica-Bold')
    moto=data.get('Moto') or data.get('Veículo') or '-'; plate=moto.split(' - ')[-1] if ' - ' in moto else moto.split('·')[-1].strip(); model=moto.rsplit(' - ',1)[0] if ' - ' in moto else moto
    _label_value(c,'PLACA',plate,margin+5*mm,top_y+22*mm,margin+30*mm,52*mm)
    _label_value(c,'MODELO',model,margin+5*mm,top_y+14*mm,margin+30*mm,52*mm)
    _label_value(c,'KM ATUAL',data.get('KM','-'),margin+5*mm,top_y+6*mm,margin+30*mm,48*mm)

    rx=margin+left_w+gap+5*mm; owner=data.get('Responsável da moto') or data.get('Responsável cadastrado') or '-'
    _txt(c,'RESPONSÁVEL OFICIAL',rx,top_y+31*mm,8.4,TEAL,'Helvetica-Bold')
    _label_value(c,'NOME',owner,rx,top_y+23*mm,rx+20*mm,right_w-28*mm)
    _label_value(c,'CNH',data.get('CNH do responsável','-'),rx,top_y+16*mm,rx+20*mm,right_w-28*mm)
    _txt(c,'UTILIZADO POR',rx,top_y+9*mm,8.4,TEAL,'Helvetica-Bold')
    _label_value(c,'NOME',data.get('Motorista que utilizou','-'),rx,top_y+2.5*mm,rx+20*mm,right_w-28*mm)
    _label_value(c,'CNH',data.get('CNH do motorista','-'),rx,top_y-4.5*mm,rx+20*mm,right_w-28*mm)

    # Itens
    table_y=123*mm; table_h=top_y-table_y-4*mm; _panel(c,margin,table_y,content,table_h)
    _txt(c,'CHECKLIST DE ITENS',margin+5*mm,table_y+table_h-8*mm,8.8,TEAL,'Helvetica-Bold')
    y=table_y+table_h-17*mm; att=0
    for label,value in items[:11]:
        c.setStrokeColor(colors.HexColor('#30383C')); c.line(margin+4*mm,y-1*mm,w-margin-4*mm,y-1*mm)
        _fit(c,label.upper(),margin+7*mm,y+1*mm,55*mm,6.5,WHITE,'Helvetica-Bold'); _status(c,value,margin+66*mm,y-1*mm)
        obs='---'
        if 'ATEN' in value.upper(): att+=1; obs=value.split('-',1)[1].strip() if '-' in value else 'Requer atenção.'
        _fit(c,obs,margin+99*mm,y+1*mm,73*mm,6.0,WHITE,'Helvetica'); y-=6.6*mm

    # Fotos reais tiradas no checklist
    m=re.search(r'-(\d+)\.pdf$',filename or ''); checklist_id=int(m.group(1)) if m else None
    photos=[]
    if checklist_id:
        photos=StoredFile.query.filter_by(entity_type='CHECKLIST',entity_id=checklist_id).order_by(StoredFile.id).all()
    photo_y=91*mm; _panel(c,margin,photo_y,content,28*mm)
    _txt(c,'FOTOS DO CHECKLIST',margin+5*mm,photo_y+21*mm,8.5,TEAL,'Helvetica-Bold')
    slots=4; gap2=3*mm; pw=(content-10*mm-gap2*(slots-1))/slots; ph=16*mm; px=margin+5*mm
    cats={'CHECKLIST_FRONT':'Frente','CHECKLIST_REAR':'Traseira','CHECKLIST_RIGHT':'Direita','CHECKLIST_LEFT':'Esquerda','CHECKLIST_DAMAGE':'Avaria'}
    for row in photos[:4]:
        c.setStrokeColor(BORDER); c.rect(px,photo_y+3*mm,pw,ph,fill=0,stroke=1)
        _draw_photo(c,_photo_bytes(row),px,photo_y+3*mm,pw,ph)
        _txt(c,cats.get(row.category,row.category.replace('CHECKLIST_','').title()),px,photo_y+1*mm,5.4,MUTED,'Helvetica-Bold'); px+=pw+gap2

    obs_y=67*mm; _panel(c,margin,obs_y,content,20*mm); _txt(c,'OBSERVAÇÃO GERAL',margin+5*mm,obs_y+13*mm,8.5,TEAL,'Helvetica-Bold')
    note=data.get('Avaria','Não informada'); just=data.get('Justificativa','-'); note=note if just=='-' else f'{note} · {just}'
    _fit(c,note,margin+5*mm,obs_y+5*mm,content-10*mm,6.5,WHITE,'Helvetica')

    sig_y=34*mm; _panel(c,margin,sig_y,content,28*mm); _txt(c,'ASSINATURAS',margin+5*mm,sig_y+21*mm,8.5,TEAL,'Helvetica-Bold')
    half=(content-8*mm)/2
    for idx,(label,name) in enumerate((('UTILIZADO POR',data.get('Motorista que utilizou','-')),('RESPONSÁVEL OFICIAL',owner))):
        x=margin+4*mm+idx*half; _txt(c,label,x+4*mm,sig_y+16*mm,6.2,WHITE,'Helvetica-Bold'); c.setStrokeColor(BORDER); c.line(x+8*mm,sig_y+7*mm,x+half-8*mm,sig_y+7*mm); c.setFont('Helvetica-Oblique',13); c.setFillColor(WHITE); c.drawCentredString(x+half/2,sig_y+10*mm,name); c.setFont('Helvetica',5.8); c.setFillColor(MUTED); c.drawCentredString(x+half/2,sig_y+3*mm,name)

    _txt(c,'Favela Llog · Controle de Veículos',margin,12*mm,6.2,TEAL,'Helvetica-Bold'); _txt(c,'Documento gerado pelo sistema',w-63*mm,12*mm,5.8,MUTED)
    c.showPage(); c.save(); buf.seek(0); return send_file(buf,mimetype='application/pdf',as_attachment=False,download_name=filename)


def init_checklist_pdf_upgrade(app):
    from . import enterprise19
    original=enterprise19._pdf_response
    def wrapper(title,rows,filename):
        if str(title).lower().startswith('checklist'):
            return checklist_pdf(title,rows,filename)
        return original(title,rows,filename)
    enterprise19._pdf_response=wrapper
