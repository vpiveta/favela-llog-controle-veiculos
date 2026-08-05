from __future__ import annotations

import os
import sys
from getpass import getpass

from scripts.common import set_project_directory


def main() -> int:
    set_project_directory()
    os.environ.pop("DATABASE_URL", None)
    try:
        from app import create_app
        from app.models import User, db
        app = create_app()
        with app.app_context():
            db.create_all()
            name = input("Nome: ").strip()
            username = input("Login: ").strip()
            password = getpass("Senha: ")
            confirm = getpass("Confirmar senha: ")
            if password != confirm:
                raise ValueError("As senhas nao conferem.")
            user = User.query.filter_by(username=username).first()
            if user:
                user.name = name
                user.role = "ADMIN"
                user.active = True
                user.must_change_password = False
                user.set_password(password)
            else:
                user = User(name=name, username=username, role="ADMIN", active=True, must_change_password=False)
                user.set_password(password)
                db.session.add(user)
            db.session.commit()
            print("Administrador local criado/atualizado com sucesso.")
        return 0
    except Exception as exc:
        print(f"ERRO: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
