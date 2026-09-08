from flask import g, has_request_context

from . import performance as perf


_ORIGINAL_OIL_STATUSES = perf.fast_build_oil_statuses
_ORIGINAL_OIL_ALERTS = perf.fast_build_oil_alerts
_INSTALLED = False


def _request_cache():
    if not has_request_context():
        return None
    cache = getattr(g, '_performance2_cache', None)
    if cache is None:
        cache = {}
        g._performance2_cache = cache
    return cache


def cached_oil_statuses(vehicle_id=None):
    """Evita recalcular a mesma situação de óleo mais de uma vez por requisição."""
    cache = _request_cache()
    if cache is None:
        return _ORIGINAL_OIL_STATUSES(vehicle_id)

    key = ('oil_statuses', int(vehicle_id) if vehicle_id is not None else None)
    if key not in cache:
        cache[key] = _ORIGINAL_OIL_STATUSES(vehicle_id)
    return cache[key]


def cached_oil_alerts(vehicle_id=None):
    """Reaproveita o cache de status ao montar os alertas do dashboard."""
    cache = _request_cache()
    if cache is None:
        return _ORIGINAL_OIL_ALERTS(vehicle_id)

    key = ('oil_alerts', int(vehicle_id) if vehicle_id is not None else None)
    if key not in cache:
        # O método original chama perf.fast_build_oil_statuses. Depois da
        # instalação abaixo, essa chamada passa pelo cache desta requisição.
        cache[key] = _ORIGINAL_OIL_ALERTS(vehicle_id)
    return cache[key]


def init_performance2(app):
    """Camada de performance segura, sem alterar regras de negócio."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # As funções do dashboard/context processor consultam os nomes globais do
    # módulo performance em tempo de execução. Substituí-las aqui faz o painel,
    # alertas e contexto global compartilharem o mesmo resultado em cada request.
    perf.fast_build_oil_statuses = cached_oil_statuses
    perf.fast_build_oil_alerts = cached_oil_alerts

    # Algumas rotas antigas guardam referência direta para estas funções.
    from . import routes
    routes.build_oil_statuses = cached_oil_statuses
    routes.build_oil_alerts = cached_oil_alerts

    # Em produção os templates não precisam ser verificados no disco a cada
    # requisição. Mantemos o comportamento de desenvolvimento quando DEBUG=True.
    if not app.debug:
        app.config['TEMPLATES_AUTO_RELOAD'] = False

    @app.after_request
    def performance2_headers(response):
        # Conteúdo estático muda somente em deploy. Permite ao celular reutilizar
        # CSS/JS/imagens entre telas sem baixar os mesmos arquivos repetidamente.
        if request_endpoint_is_static():
            response.headers.setdefault('Cache-Control', 'public, max-age=86400')
        return response


def request_endpoint_is_static():
    if not has_request_context():
        return False
    from flask import request
    return request.endpoint == 'static'
