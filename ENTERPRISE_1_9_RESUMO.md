# Enterprise 1.9 - Login por placa, pendências e PDFs

## Alterações
- Motorista entra com usuário, senha e placa da moto.
- Placa própria ou sem responsável libera acesso normalmente.
- Placa de outro motorista exige justificativa e aprovação do Gerente/Admin.
- Veículo ativo fica visível na sessão.
- Uso temporário mostra último abastecimento e última manutenção no dashboard.
- Abastecimento e manutenção podem ser lançados em qualquer moto da própria base.
- Lançamentos guardam responsável oficial da moto e quem realizou o lançamento.
- Checklist com item em Atenção exige motivo.
- Atenção cria pendência persistente da moto.
- Pendência permanece para motorista e gerente até ser resolvida por manutenção vinculada.
- PDFs de checklist, abastecimento e manutenção podem ser abertos e compartilhados pelo celular/WhatsApp.
- Dashboard continua sem bloco redundante de Frota.

## Rollback
A main não deve ser alterada antes da homologação. O commit anterior da produção permanece como ponto de retorno.
