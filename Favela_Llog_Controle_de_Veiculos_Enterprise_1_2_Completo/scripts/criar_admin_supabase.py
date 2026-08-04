from __future__ import annotations

import os
import sys
from getpass import getpass

from common import load_env_file, set_project_directory


def main() -> int:
    set_project_directory()
    load_env_file()
    if not os.getenv("DATABASE_URL"):
        print("ERRO: DATABASE_URL nao configurada. Execute CONFIGURAR_SUPABASE.bat.")
        return 1
    try:
        from app import create_app
        from app.models import User, db
        app = create_app()
        with app.app_context():
            db.create_all()
            print("=" * 58)
            print(" CRIAR / ATUALIZAR ADMINISTRADOR NO SUPABASE")
            print("=" * 58)
            name = input("Nome: ").strip()
            username = input("Login: ").strip()
            password = getpass("Senha: ")
            confirm = getpass("Confirmar senha: ")
            if not name or not username or len(password) < 6:
                raise ValueError("Preencha nome/login e use senha com no minimo 6 caracteres.")
            if password != confirm:
                raise ValueError("As senhas nao conferem.")
            user = User.query.filter_by(username=username).first()
            if user:
                user.name = name
                user.role = "ADMIN"
                user.active = True
                user.must_change_password = False
                user.set_password(password)
                action = "atualizado"
            else:
                user = User(name=name, username=username, role="ADMIN", active=True, must_change_password=False)
                user.set_password(password)
                db.session.add(user)
                action = "criado"
            db.session.commit()
            print(f"\nAdministrador {action} com sucesso no Supabase.")
            print(f"Login: {username}")
        return 0
    except Exception as exc:
        print(f"\nERRO: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
