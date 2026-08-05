from __future__ import annotations

import os
import sys

from scripts.common import load_env_file, set_project_directory


def main() -> int:
    set_project_directory()
    load_env_file()
    if not os.getenv("DATABASE_URL"):
        print("ERRO: DATABASE_URL nao configurada. Execute CONFIGURAR_SUPABASE.bat.")
        return 1
    try:
        from sqlalchemy import text
        from app import create_app
        from app.models import db
        app = create_app()
        with app.app_context():
            db.session.execute(text("SELECT 1"))
            db.create_all()
            db.session.commit()
        print("OK: conexao com Supabase validada e tabelas verificadas.")
        return 0
    except Exception as exc:
        print(f"ERRO ao conectar no Supabase: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
