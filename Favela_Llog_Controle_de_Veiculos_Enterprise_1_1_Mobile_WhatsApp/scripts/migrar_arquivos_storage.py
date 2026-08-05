from datetime import datetime
from app import create_app
from app.models import db, StoredFile
from app.storage import is_configured, upload_bytes


def main():
    app = create_app()
    with app.app_context():
        if not is_configured():
            raise SystemExit('Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY antes da migração.')
        rows = StoredFile.query.filter(StoredFile.storage_path.is_(None)).order_by(StoredFile.id).all()
        total = len(rows)
        migrated = 0
        skipped = 0
        print(f'Arquivos pendentes: {total}')
        for index, item in enumerate(rows, 1):
            if not item.content:
                print(f'[{index}/{total}] SEM CONTEÚDO: {item.original_name}')
                skipped += 1
                continue
            path = f"{item.entity_type.lower()}/{item.entity_id}/{item.category.lower()}/{item.token}-{item.original_name}"
            try:
                result = upload_bytes(path, bytes(item.content), item.mime_type, upsert=True)
                item.storage_bucket = result.bucket
                item.storage_path = result.path
                item.storage_migrated_at = datetime.utcnow()
                # Só limpa o binário depois de confirmar o upload.
                item.content = b''
                db.session.commit()
                migrated += 1
                print(f'[{index}/{total}] OK: {item.original_name}')
            except Exception as exc:
                db.session.rollback()
                print(f'[{index}/{total}] ERRO: {item.original_name} -> {exc}')
        print(f'Concluído. Migrados: {migrated}. Sem conteúdo: {skipped}.')

if __name__ == '__main__':
    main()
