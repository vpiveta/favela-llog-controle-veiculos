import click
from flask.cli import with_appcontext
from .models import db, User

def register_cli(app):
    @app.cli.command('create-admin')
    @with_appcontext
    def create_admin():
        name = click.prompt('Nome')
        username = click.prompt('Login')
        password = click.prompt('Senha', hide_input=True, confirmation_prompt=True)
        if User.query.filter_by(username=username).first():
            click.echo('Login já existe.')
            return
        user = User(name=name, username=username, role='ADMIN', must_change_password=False)
        user.set_password(password)
        db.session.add(user); db.session.commit()
        click.echo('Administrador criado com sucesso.')
