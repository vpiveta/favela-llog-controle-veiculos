from __future__ import annotations

import secrets
import sys

from scripts.common import load_env_file, normalize_database_url, set_project_directory, write_env


def main() -> int:
    set_project_directory()
    load_env_file()
    print("=" * 62)
    print(" FAVELA LLOG CONTROLE DE VEICULOS - CONFIGURAR SUPABASE")
    print("=" * 62)
    print("Cole a Connection String do Supabase (Session Pooler recomendado).")
    print("A informacao sera salva apenas no arquivo local .env, ignorado pelo Git.")
    print("\nIMPORTANTE: a conexao ficara visivel enquanto voce cola ou digita.")
    print("Use Ctrl+V ou clique com o botao direito dentro desta janela.")
    database_url = normalize_database_url(input("DATABASE_URL: "))
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        print("ERRO: a conexao precisa iniciar com postgresql://")
        return 1
    app_url = input("URL online do sistema (opcional): ").strip()
    write_env({
        "DATABASE_URL": database_url,
        "SECRET_KEY": secrets.token_urlsafe(48),
        "APP_URL": app_url,
    })
    print("\nConfiguracao salva com sucesso em .env.")
    print("Agora execute TESTAR_BANCO.bat e depois CRIAR_ADMIN_SUPABASE.bat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
