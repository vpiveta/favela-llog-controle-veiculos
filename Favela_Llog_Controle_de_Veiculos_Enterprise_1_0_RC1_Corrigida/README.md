# Favela Llog Controle de Veículos — Enterprise 1.0

Sistema independente para controle de custos da frota própria.

## Funcionalidades
- Login por perfil: Administrador e Motorista.
- Motorista visualiza apenas a própria moto e os próprios lançamentos.
- Cadastro de veículos e vínculo com motoristas.
- Abastecimento com data, valor, litros, quilometragem, posto e foto da nota.
- Manutenção com período, serviço no mesmo dia, descrição, oficina, valor e foto.
- Alerta de troca de óleo por quilometragem e prazo.
- Dashboard administrativo por tipo de custo, motorista e veículo.
- Configuração de destinatários para alertas por e-mail.

## Primeiro acesso local
1. Execute `INICIAR_LOCAL.bat` uma vez.
2. Em outro terminal, execute `CRIAR_ADMIN.bat`.
3. Acesse `http://127.0.0.1:5000`.

## Produção
Configure `DATABASE_URL` com um PostgreSQL/Supabase e publique no Render.

## Versão RC1 corrigida
- Dependência PostgreSQL compatível com Python 3.13 (`psycopg[binary] 3.2.13`).
- Script de criação do administrador corrigido.
- Homologação automática incluída em `TESTAR_HOMOLOGACAO.bat`.
- Ambiente virtual não é distribuído no ZIP; ele é criado automaticamente no primeiro uso.
