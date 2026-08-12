# Favela Llog Controle de Veículos — Produção Consolidada

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


## Versão 1.1 — Mobile e WhatsApp assistido
- Abastecimento simplificado: data, valor, combustível, litros/posto opcionais e foto obrigatória.
- Quilometragem e observação removidas do abastecimento.
- Câmera traseira aberta pelo navegador móvel com `capture=environment`.
- Pré-visualização e compressão da foto antes do envio, quando suportado.
- Alertas de óleo preparados automaticamente e enviados pelo WhatsApp normal após confirmação manual.
- Não utiliza Meta API, robôs ou bibliotecas não oficiais.

## Versao 1.2 — Pacote consolidado
- Assistente `MENU_FAVELA_LLOG.bat` para operacoes locais e online.
- Configuracao do Supabase sem PowerShell e sem depender do nome da pasta.
- Criacao/redefinicao do administrador online diretamente no PostgreSQL.
- Teste de conexao e criacao das tabelas do Supabase.
- Publicacao GitHub/Render por BAT.
- Python fixado em 3.12.7 para o Render.

## Versão 1.6 — Tema azul-água e operação completa
- Nova identidade visual azul-água em telas, fundo e marca.
- Checklists separados de retirada e devolução.
- Itens adicionais: carregador, suporte de celular, baú e alforje.
- Abastecimento com KM atual obrigatório e somente gasolina.
- Moto do abastecimento selecionada automaticamente pela retirada ativa do motorista.
- Checklist de devolução encerra a moto temporária e restaura a moto própria no abastecimento.
- Horários exibidos corretamente no fuso `America/Sao_Paulo`.
- Migração automática e compatível com bancos existentes.

## Versão 1.7 — Carros, motos em manutenção e custo de óleo corrigido
- O valor de troca de óleo passa a ser informado separadamente e deixa de usar automaticamente o total da nota de manutenção.
- O ciclo de 990 km continua baseado nos hodômetros dos checklists diários e reinicia no KM da troca.
- Nova visão de motos em manutenção, exibindo o motorista vinculado e permitindo ao ADM concluir o serviço.
- Cadastro de veículos diferencia Moto e Carro sem alterar os registros antigos, que permanecem como motos.
- Abastecimento de carro com foto da nota e seleção obrigatória do ADM autorizador.
- Valores, históricos e comprovantes de carros ficam separados dos registros das motos.
- Migrações leves, automáticas e idempotentes preservam os bancos SQLite e PostgreSQL/Supabase existentes.

### Versão 1.7.1 — Identificação do carro
- Foto da placa obrigatória em todo abastecimento de carro.
- Foto da placa armazenada separadamente da nota do abastecimento.
- Opções independentes para abrir e baixar a nota e a foto da placa no histórico.
