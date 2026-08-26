import os
from pathlib import Path

os.environ.setdefault('SECRET_KEY', 'enterprise19-test')
os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/favela_llog_enterprise19.db')

from app import create_app
from app.models import db, User, Vehicle, VehicleUseRequest, VehicleIssue, DailyChecklist

DB_PATH = Path('/tmp/favela_llog_enterprise19.db')
if DB_PATH.exists(): DB_PATH.unlink()
app = create_app()
app.config.update(TESTING=True)


def make_user(name, username, role, base, password='123456'):
    u=User(name=name,username=username,role=role,base_code=base,active=True,must_change_password=False)
    u.set_password(password);db.session.add(u);db.session.flush();return u

with app.app_context():
    db.drop_all();db.create_all()
    manager=make_user('Gerente SDA9','gerente','ADMIN_BASE','SDA9')
    a=make_user('Motorista A','motoristaa','DRIVER','SDA9')
    b=make_user('Motorista B','motoristab','DRIVER','SDA9')
    other=make_user('Motorista Outra Base','outro','DRIVER','SLI9')
    va=Vehicle(plate='ABC1D23',brand='Honda',model='CG',vehicle_type='MOTORCYCLE',base_code='SDA9',driver_id=a.id,current_km=1000)
    vb=Vehicle(plate='XYZ9K88',brand='Honda',model='Biz',vehicle_type='MOTORCYCLE',base_code='SDA9',driver_id=b.id,current_km=2000)
    vo=Vehicle(plate='SLI1A11',brand='Honda',model='CG',vehicle_type='MOTORCYCLE',base_code='SLI9',driver_id=other.id)
    db.session.add_all([va,vb,vo]);db.session.commit()
    va_id,vb_id,a_id,b_id=va.id,vb.id,a.id,b.id

client=app.test_client()
# Placa própria libera acesso.
r=client.post('/login',data={'username':'motoristaa','password':'123456','plate':'ABC1D23'},follow_redirects=True)
assert r.status_code==200 and 'VEÍCULO ATIVO' in r.get_data(as_text=True)
client.get('/logout')

# Outra base não pode ser utilizada.
r=client.post('/login',data={'username':'motoristaa','password':'123456','plate':'SLI1A11'},follow_redirects=True)
assert 'Placa não encontrada na sua base' in r.get_data(as_text=True)

# Moto de outro motorista exige justificativa e cria solicitação.
r=client.post('/login',data={'username':'motoristaa','password':'123456','plate':'XYZ9K88'},follow_redirects=True)
assert 'Informe a justificativa' in r.get_data(as_text=True)
r=client.post('/login',data={'username':'motoristaa','password':'123456','plate':'XYZ9K88','justification':'Moto titular em manutenção'},follow_redirects=True)
assert 'Solicitação enviada ao gerente' in r.get_data(as_text=True)
with app.app_context():
    req=VehicleUseRequest.query.filter_by(requester_id=a_id,vehicle_id=vb_id,status='PENDING').first();assert req
    req_id=req.id

# Gerente aprova.
r=client.post('/login',data={'username':'gerente','password':'123456'},follow_redirects=True)
assert r.status_code==200
r=client.post(f'/admin/vehicle-use/{req_id}/approve',follow_redirects=True);assert r.status_code==200
client.get('/logout')

# Novo login com a placa aprovada libera uso temporário.
r=client.post('/login',data={'username':'motoristaa','password':'123456','plate':'XYZ9K88'},follow_redirects=True)
text=r.get_data(as_text=True)
assert 'Uso temporário autorizado' in text and 'XYZ9K88' in text

# Evento de checklist com Atenção gera pendência persistente.
with app.app_context():
    with app.test_request_context('/checklist/new',method='POST',data={
        'tires_ok':'attention','tires_ok_reason':'Pneu traseiro com desgaste',
        'brakes_ok':'ok','lights_ok':'ok','indicators_ok':'ok','mirrors_ok':'ok','horn_ok':'ok','chain_ok':'ok',
        'charger_ok':'ok','phone_holder_ok':'ok','top_case_ok':'ok','saddlebags_ok':'ok','general_condition':'GOOD'
    }):
        c=DailyChecklist(driver_id=a_id,vehicle_id=vb_id,owner_driver_id=b_id,borrowed_vehicle=True,borrow_reason='Teste',odometer=2100,
            tires_ok=False,brakes_ok=True,lights_ok=True,indicators_ok=True,mirrors_ok=True,horn_ok=True,chain_ok=True,charger_ok=True,
            phone_holder_ok=True,top_case_ok=True,saddlebags_ok=True,general_condition='GOOD',has_damage=False,status='COMPLETED',share_token='enterprise19-test-token')
        db.session.add(c);db.session.commit();cid=c.id
    issue=VehicleIssue.query.filter_by(checklist_id=cid,item_code='tires_ok',status='OPEN').first();assert issue and 'desgaste' in issue.description

# PDF do checklist abre.
r=client.get(f'/checklist/{cid}/pdf');assert r.status_code==200 and r.mimetype=='application/pdf' and len(r.data)>500
print('ENTERPRISE 1.9: homologacao automatica aprovada')
