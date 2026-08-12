# Enterprise 1.6 — Checklist de devolução e tema azul-água

## Alterações entregues

- Identidade visual azul-água `#38D6D0`, incluindo fundo e imagem da marca.
- Fluxos separados para checklist de retirada e checklist de devolução.
- Novos itens obrigatórios no checklist: carregador, suporte de celular, baú e alforje.
- Abastecimento com quilometragem atual obrigatória.
- Tipo de combustível fixado e validado no servidor como gasolina.
- Para motoristas, o abastecimento usa automaticamente a moto informada na última retirada ativa.
- O checklist de devolução encerra o uso temporário; o próximo abastecimento volta para a moto própria.
- Timestamps continuam armazenados em UTC e são exibidos em `America/Sao_Paulo`.

## Atualização do banco

Ao iniciar, o sistema cria automaticamente e de forma idempotente as novas colunas em `daily_checklist`. Os registros antigos são preservados como histórico e não ativam automaticamente uma moto emprestada antiga.

## Configuração opcional

O fuso padrão é São Paulo. Para alterar, defina `APP_TIMEZONE` com um identificador IANA válido.
