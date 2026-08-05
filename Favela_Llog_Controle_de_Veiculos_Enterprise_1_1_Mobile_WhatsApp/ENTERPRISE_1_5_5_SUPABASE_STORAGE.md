# Enterprise 1.5.5 — Supabase Storage

## Dados operacionais
Usuários, motoristas, veículos, checklists, abastecimentos, manutenções, alertas e auditoria permanecem no PostgreSQL do Supabase pela variável `DATABASE_URL`.

## Fotos e comprovantes
Novos arquivos são enviados ao Supabase Storage quando as variáveis abaixo estão configuradas:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_STORAGE_BUCKET` (opcional; padrão: `controle-veiculos`)

O bucket é criado automaticamente como privado no primeiro envio.

## Compatibilidade e preservação
- Arquivos antigos salvos no PostgreSQL continuam abrindo normalmente.
- O script `MIGRAR_ARQUIVOS_SUPABASE_STORAGE.bat` envia os arquivos antigos para o Storage.
- O conteúdo antigo só é removido do PostgreSQL depois que cada upload é confirmado.
- Arquivos que já foram perdidos pelo disco temporário do Render não podem ser recuperados automaticamente.

## Variáveis no Render
Não coloque a Service Role no GitHub. Cadastre somente em Render > Environment.
