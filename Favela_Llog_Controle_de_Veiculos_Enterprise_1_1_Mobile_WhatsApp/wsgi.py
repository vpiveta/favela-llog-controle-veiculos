from app import create_app

app = create_app()

# Performance 2.0 é aplicada depois da criação completa da aplicação para
# reutilizar as otimizações existentes sem alterar regras de negócio.
from app.performance2 import init_performance2
init_performance2(app)

# Performance 2.1: pagina históricos pesados e mantém totais agregados no banco.
from app.performance21 import init_performance21
init_performance21(app)
