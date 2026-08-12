# Enterprise 1.7 — Carros, manutenção e óleo

## Entregas

- Valor financeiro da troca de óleo separado do valor total da manutenção.
- Controle do ciclo de 990 km calculado a partir dos hodômetros dos checklists.
- Painel dedicado às motos em manutenção, com motorista vinculado, serviço, datas e conclusão pelo ADM.
- Cadastro de veículos com os tipos `Moto` e `Carro`.
- Abastecimento de carro com gasolina, KM, nota e ADM autorizador obrigatório.
- Histórico, totais e comprovantes separados entre carros e motos.
- Notificação administrativa específica para abastecimento de carro.
- Foto obrigatória da placa do carro, com armazenamento, abertura e download separados da nota.

## Compatibilidade do banco

A inicialização cria apenas as colunas ausentes. Nenhuma tabela é apagada e nenhum
registro anterior é removido. Veículos e despesas antigos continuam classificados
como motos. Trocas antigas permanecem válidas para o ciclo de KM; como não possuíam
valor de óleo discriminado, não geram um custo financeiro inventado no novo card.
