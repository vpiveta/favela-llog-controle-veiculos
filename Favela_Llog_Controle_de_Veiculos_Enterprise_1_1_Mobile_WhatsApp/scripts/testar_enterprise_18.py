import os
from pathlib import Path

os.environ.setdefault('SECRET_KEY', 'enterprise18-test')
os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/favela_llog_enterprise18.db')

from app import create_app
from app.models import db, User, Vehicle

DB_PATH = Path('/tmp/favela_llog_enterprise18.db')
if DB_PATH.exists():
    DB_PATH.unlink()

app = create_app()
app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)


def make_user(name, username, role, base, password='123456'):
    u = User(name=name, username=username, role=role, base_code=base, active=True, must_change_password=False)
    u.set_password(password)
    db.session.add(u)
    db.session.flush()
    return u


with app.app_context():
    db.drop_all()
    db.create_all()
    global_admin = make_user('Admin Geral', 'global', 'ADMIN', 'SDA9')
    sda_manager = make_user('Gerente SDA9', 'gerentesda', 'ADMIN_BASE', 'SDA9')
    sli_manager = make_user('Gerente SLI9', 'gerentesli', 'ADMIN_BASE', 'SLI9')
    sda_driver = make_user('Motorista SDA', 'driversda', 'DRIVER', 'SDA9')
    sli_driver = make_user('Motorista SLI', 'driversli', 'DRIVER', 'SLI9')
    db.session.add(Vehicle(plate='SDA1A11', brand='Honda', model='CG', vehicle_type='MOTORCYCLE', base_code='SDA9', driver_id=sda_driver.id))
    db.session.add(Vehicle(plate='SLI1A11', brand='Honda', model='CG', vehicle_type='MOTORCYCLE', base_code='SLI9', driver_id=sli_driver.id))
    db.session.commit()
    sda_driver_id = sda_driver.id
    sli_driver_id = sli_driver.id


def login(client, username):
    r = client.post('/login', data={'username': username, 'password': '123456'}, follow_redirects=True)
    assert r.status_code == 200, (username, r.status_code)


# Gerente SLI9 não enxerga SDA9.
client = app.test_client()
login(client, 'gerentesli')
r = client.get('/admin/users')
assert r.status_code == 200
text = r.get_data(as_text=True)
assert 'Motorista SLI' in text
assert 'Motorista SDA' not in text
assert 'Gerente SDA9' not in text

# Gerente SLI9 não consegue editar usuário da SDA9.
r = client.post(f'/admin/users/{sda_driver_id}/edit', data={
    'name': 'Tentativa indevida', 'username': 'driversda', 'active': 'on'
})
assert r.status_code in (403, 404)

# Relatório do gerente permanece no escopo da base.
r = client.get('/admin/checklist-report')
assert r.status_code == 200

# Admin Geral enxerga as duas bases.
client.get('/logout')
login(client, 'global')
r = client.get('/admin/users')
assert r.status_code == 200
text = r.get_data(as_text=True)
assert 'Motorista SDA' in text and 'Motorista SLI' in text
assert 'SDA9' in text and 'SLI9' in text

# Edição de nome preserva o mesmo ID.
r = client.post(f'/admin/users/{sli_driver_id}/edit', data={
    'name': 'Motorista SLI Editado', 'username': 'driversli', 'base_code': 'SLI9',
    'role': 'DRIVER', 'active': 'on', 'phone': '11999999999'
}, follow_redirects=True)
assert r.status_code == 200
with app.app_context():
    u = db.session.get(User, sli_driver_id)
    assert u.name == 'Motorista SLI Editado'
    assert u.base_code == 'SLI9'
    assert u.phone == '11999999999'

print('ENTERPRISE 1.8: homologacao automatica aprovada')
