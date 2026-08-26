import os
from pathlib import Path

os.environ.setdefault('SECRET_KEY', 'enterprise19-test')
os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/favela_llog_enterprise19.db')

from app import create_app
from app.models import db, User, Vehicle, VehicleUseRequest, VehicleIssue, DailyChecklist
from app.enterprise19_wait import DriverDocument

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

# Primeiro acesso do motorista exige CNH somente uma vez.
driver=app.test_client()
r=driver.post('/login',data={'username':'motoristaa','password':'123456','plate':'ABC1D23'},follow_redirects=True)
text=r.get_data(as_text=True)
assert r.status_code==200 and 'Complete seu cadastro' in text and 'Número da CNH' in text
r=driver.post('/meu-cadastro/cnh',data={'cnh_number':'12345678901'},follow_redirects=True)
text=r.get_data(as_text=True)
assert r.status_code==200 and 'VEÍCULO ATIVO' in text
with app.app_context():
    doc=DriverDocument.query.filter_by(user_id=a_id).first();assert doc and doc.cnh_number=='12345678901'
driver.get('/logout')

# Segundo acesso não pede CNH novamente.
r=driver.post('/login',data={'username':'motoristaa','password':'123456','plate':'ABC1D23'},follow_redirects=True)
assert 'Complete seu cadastro' not in r.get_data(as_text=True) and 'VEÍCULO ATIVO' in r.get_data(as_text=True)
driver.get('/logout')

# Outra base não pode ser utilizada.
r=driver.post('/login',data={'username':'motoristaa','password':'123456','plate':'SLI1A11'},follow_redirects=True)
assert 'Placa não encontrada na sua base' in r.get_data(as_text=True)

# Moto de outro motorista exige justificativa e entra em tela de aguarde.
r=driver.post('/login',data={'username':'motoristaa','password':'123456','plate':'XYZ9K88'},follow_redirects=True)
assert 'Informe a justificativa' in r.get_data(as_text=True)
r=driver.post('/login',data={'username':'motoristaa','password':'123456','plate':'XYZ9K88','justification':'Moto titular em manutenção'},follow_redirects=True)
text=r.get_data(as_text=True)
assert 'Aguardando autorização' in text and 'Aguardando o gerente da base autorizar' in text
with app.app_context():
    req=VehicleUseRequest.query.filter_by(requester_id=a_id,vehicle_id=vb_id,status='PENDING').first();assert req
    req_id=req.id

# Enquanto pendente, motorista continua bloqueado e não recebe sessão autenticada.
r=driver.get('/aguardando-autorizacao/status')
assert r.get_json()['status']=='PENDING'
r=driver.get('/')
assert r.status_code in (302,401)

# Gerente aprova em outra sessão.
manager_client=app.test_client()
r=manager_client.post('/login',data={'username':'gerente','password':'123456'},follow_redirects=True)
assert r.status_code==200
r=manager_client.post(f'/admin/vehicle-use/{req_id}/approve',follow_redirects=True);assert r.status_code==200

# A tela do motorista detecta aprovação e libera automaticamente, sem novo login.
r=driver.get('/aguardando-autorizacao/status')
data=r.get_json();assert data['status']=='APPROVED' and data.get('redirect')
r=driver.get(data['redirect'],follow_redirects=True)
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

# PDF do checklist abre com o novo documento do motorista disponível no perfil.
r=driver.get(f'/checklist/{cid}/pdf');assert r.status_code==200 and r.mimetype=='application/pdf' and len(r.data)>500

# Recusa não libera acesso.
driver2=app.test_client()
r=driver2.post('/login',data={'username':'motoristaa','password':'123456','plate':'XYZ9K88','justification':'Segundo teste'},follow_redirects=True)
with app.app_context():
    denied_req=VehicleUseRequest.query.filter_by(requester_id=a_id,vehicle_id=vb_id,status='PENDING').order_by(VehicleUseRequest.id.desc()).first();assert denied_req
    denied_id=denied_req.id
manager_client.post(f'/admin/vehicle-use/{denied_id}/deny',follow_redirects=True)
r=driver2.get('/aguardando-autorizacao/status')
assert r.get_json()['status']=='DENIED'
r=driver2.get('/')
assert r.status_code in (302,401)

print('ENTERPRISE 1.9: homologacao automatica aprovada')
