import os

# Configuração pensada para uma aplicação Flask majoritariamente ligada a I/O
# (Supabase/PostgreSQL e arquivos). Um único worker com múltiplas threads evita
# consumo excessivo de memória em instâncias pequenas do Render e melhora a
# capacidade de atender mais de uma requisição ao mesmo tempo.
workers = int(os.getenv('WEB_CONCURRENCY', '1'))
threads = int(os.getenv('GUNICORN_THREADS', '4'))
worker_class = 'gthread'
timeout = int(os.getenv('GUNICORN_TIMEOUT', '120'))
graceful_timeout = 30
keepalive = 5

# Reinicia o processo ocasionalmente para limitar crescimento de memória em uso
# contínuo sem causar reinícios frequentes.
max_requests = int(os.getenv('GUNICORN_MAX_REQUESTS', '1500'))
max_requests_jitter = int(os.getenv('GUNICORN_MAX_REQUESTS_JITTER', '150'))
