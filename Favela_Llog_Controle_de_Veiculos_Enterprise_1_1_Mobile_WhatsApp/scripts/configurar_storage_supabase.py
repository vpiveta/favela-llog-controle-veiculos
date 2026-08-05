from __future__ import annotations
import sys
from scripts.common import load_env_file, set_project_directory, write_env


def main() -> int:
    set_project_directory()
    load_env_file()
    print('=' * 66)
    print(' FAVELA LLOG - CONFIGURAR SUPABASE STORAGE')
    print('=' * 66)
    print('Use Project Settings > API no Supabase.')
    print('A SERVICE ROLE e secreta: nunca envie para o GitHub ou navegador.')
    url = input('SUPABASE_URL: ').strip().rstrip('/')
    key = input('SUPABASE_SERVICE_ROLE_KEY: ').strip()
    bucket = input('Nome do bucket [controle-veiculos]: ').strip() or 'controle-veiculos'
    if not url.startswith('https://') or '.supabase.co' not in url:
        print('ERRO: SUPABASE_URL inválida.')
        return 1
    if not key:
        print('ERRO: informe a Service Role Key.')
        return 1
    write_env({
        'SUPABASE_URL': url,
        'SUPABASE_SERVICE_ROLE_KEY': key,
        'SUPABASE_STORAGE_BUCKET': bucket,
    })
    print('\nStorage configurado no .env local.')
    print('Cadastre as mesmas 3 variáveis em Render > Environment.')
    print('Depois publique e execute MIGRAR_ARQUIVOS_SUPABASE_STORAGE.bat.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
