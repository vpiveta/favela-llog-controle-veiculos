import base64
import json
import os
import re
from datetime import timedelta

import requests
from flask import current_app, flash, g, redirect, request, url_for
from flask_login import current_user

from .models import db, Expense, OilChange, StoredFile, VehicleIssue, AuditLog
from .storage import download_bytes, SupabaseStorageError
from .time_utils import utc_now

AI_MARKER = '[IA-NOTA]'
MODEL = os.getenv('OPENAI_RECEIPT_MODEL', 'gpt-5.6-luna')


def _receipt_record(expense):
    return StoredFile.query.filter(
        StoredFile.entity_id == expense.id,
        StoredFile.entity_type.in_(('EXPENSE', 'MOTORCYCLE_EXPENSE', 'CAR_EXPENSE')),
        StoredFile.category.in_(('RECEIPT', 'MOTORCYCLE_RECEIPT', 'CAR_FUEL_RECEIPT')),
    ).order_by(StoredFile.id.desc()).first()


def _receipt_bytes(expense):
    stored = _receipt_record(expense)
    if not stored:
        return None, None, None
    if stored.is_in_storage:
        data, mime = download_bytes(stored.storage_bucket, stored.storage_path)
    else:
        data, mime = stored.content, stored.mime_type
    return data or None, mime or stored.mime_type or 'application/octet-stream', stored


def _extract_response_text(payload):
    direct = payload.get('output_text')
    if direct:
        return direct
    parts = []
    for item in payload.get('output') or []:
        for content in item.get('content') or []:
            text = content.get('text')
            if text:
                parts.append(text)
    return '\n'.join(parts)


def _parse_json(text):
    text = (text or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I | re.S).strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r'\{.*\}', text, re.S)
        if not match:
            raise ValueError('A IA não retornou JSON válido.')
        return json.loads(match.group(0))


def analyze_receipt(expense, data, mime_type, filename='nota'):
    api_key = (os.getenv('OPENAI_API_KEY') or '').strip()
    if not api_key:
        return None
    prompt = (
        'Analise esta nota/comprovante de veículo. Retorne SOMENTE JSON válido com: '
        'services (array de serviços/peças efetivamente identificados), oil_change (boolean), '
        'odometer (inteiro ou null), workshop (string ou null), total_amount (number ou null), '
        'document_date (YYYY-MM-DD ou null), confidence (0 a 1) e summary (string curta). '
        'Não invente informação. Se não estiver legível, use null ou lista vazia. '
        'Considere troca de óleo apenas quando a nota indicar óleo/troca de óleo de forma clara.'
    )
    encoded = base64.b64encode(data).decode('ascii')
    if mime_type == 'application/pdf' or filename.lower().endswith('.pdf'):
        attachment = {'type': 'input_file', 'filename': filename or 'nota.pdf', 'file_data': encoded}
    else:
        attachment = {'type': 'input_image', 'image_url': f'data:{mime_type};base64,{encoded}', 'detail': 'high'}
    response = requests.post(
        'https://api.openai.com/v1/responses',
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json={'model': MODEL, 'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': prompt}, attachment]}]},
        timeout=90,
    )
    if response.status_code >= 400:
        raise RuntimeError(f'Falha na análise da nota: HTTP {response.status_code} - {response.text[:300]}')
    return _parse_json(_extract_response_text(response.json()))


def _normalize_services(values):
    clean, seen = [], set()
    for value in values or []:
        text = re.sub(r'\s+', ' ', str(value or '')).strip(' -;,.')
        key = text.casefold()
        if text and key not in seen:
            seen.add(key); clean.append(text)
    return clean


def _issue_matches(issue, services_text):
    source = f'{issue.item_label or ""} {issue.description or ""}'.casefold()
    target = services_text.casefold()
    aliases = {
        'freio': ('freio', 'pastilha', 'sapata', 'disco'), 'pneu': ('pneu', 'roda', 'câmara', 'camara'),
        'luz': ('luz', 'farol', 'lanterna', 'lâmpada', 'lampada'), 'seta': ('seta', 'indicador'),
        'buzina': ('buzina',), 'corrente': ('corrente', 'relação', 'relacao', 'coroa', 'pinhão', 'pinhao'),
        'retrovisor': ('retrovisor', 'espelho'), 'óleo': ('óleo', 'oleo', 'lubrificante', 'filtro de óleo', 'filtro de oleo'),
        'suporte': ('suporte',), 'baú': ('baú', 'bau', 'baga'),
    }
    for words in aliases.values():
        if any(word in source for word in words) and any(word in target for word in words):
            return True
    tokens = [t for t in re.findall(r'[a-záàâãéêíóôõúç]{4,}', source) if t not in {'moto', 'item', 'problema', 'avaria'}]
    return any(token in target for token in tokens)


def apply_analysis(expense, analysis, actor_id=None):
    if not analysis:
        return False
    vehicle = expense.vehicle
    changed = False
    services = _normalize_services(analysis.get('services'))
    try: confidence = float(analysis.get('confidence') or 0)
    except Exception: confidence = 0.0
    try: ai_km = int(analysis.get('odometer')) if analysis.get('odometer') is not None else None
    except Exception: ai_km = None
    if ai_km is not None and ai_km >= 0:
        expense.odometer = max(expense.odometer or 0, ai_km)
        if ai_km > (vehicle.current_km or 0): vehicle.current_km = ai_km; changed = True
    if expense.maintenance:
        detail = expense.maintenance
        original = detail.description or ''
        extras = [s for s in services if s.casefold() not in original.casefold()]
        if extras:
            detail.description = original.rstrip() + f"\n{AI_MARKER} Serviços adicionais identificados na nota: " + '; '.join(extras); changed = True
        if analysis.get('workshop') and not detail.workshop:
            detail.workshop = str(analysis.get('workshop')).strip()[:160] or None; changed = True
        if bool(analysis.get('oil_change')) and confidence >= 0.60:
            detail.is_oil_change = True
            base_km = expense.odometer or vehicle.current_km or 0
            existing = OilChange.query.filter_by(expense_id=expense.id).first()
            if base_km > 0 and not existing:
                db.session.add(OilChange(change_date=expense.expense_date, odometer=base_km, next_change_km=base_km + 990, next_change_date=None, oil_type=None, vehicle_id=vehicle.id, expense_id=expense.id)); changed = True
        if services and confidence >= 0.60:
            services_text = ' '.join(services)
            for issue in VehicleIssue.query.filter_by(vehicle_id=vehicle.id, status='OPEN').all():
                if _issue_matches(issue, services_text):
                    issue.status = 'RESOLVED'; issue.resolved_at = utc_now(); issue.resolved_by_id = actor_id or expense.created_by_id; issue.maintenance_expense_id = expense.id; changed = True
    note = expense.notes or ''
    if AI_MARKER not in note:
        summary = str(analysis.get('summary') or '').strip()
        services_label = '; '.join(services) if services else 'nenhum serviço adicional confirmado'
        audit_note = f'{AI_MARKER} Nota analisada por IA. Serviços: {services_label}'
        if summary: audit_note += f'. Resumo: {summary}'
        expense.notes = (note.rstrip() + ('\n' if note.strip() else '') + audit_note)[:10000]; changed = True
    if changed and actor_id:
        db.session.add(AuditLog(action='AI_RECEIPT_SYNC', entity_type='EXPENSE', entity_id=expense.id, description=f'Nota analisada por IA e ficha do veículo {vehicle.plate} sincronizada.', user_id=actor_id))
    return changed


def process_expense(expense, actor_id=None, force=False):
    if not expense or expense.is_deleted or expense.asset_type != 'MOTORCYCLE': return False
    if not force and AI_MARKER in (expense.notes or ''): return False
    data, mime, stored = _receipt_bytes(expense)
    if not data: return False
    analysis = analyze_receipt(expense, data, mime, stored.original_name if stored else 'nota')
    if not analysis: return False
    changed = apply_analysis(expense, analysis, actor_id=actor_id)
    if changed: db.session.commit()
    return changed


def reprocess_existing(actor_id=None, limit=None):
    query = Expense.query.filter(Expense.asset_type == 'MOTORCYCLE', Expense.is_deleted.is_(False), Expense.expense_type.in_(('MAINTENANCE', 'FUEL'))).order_by(Expense.expense_date.asc(), Expense.id.asc())
    processed = changed = 0
    for expense in query.all():
        if AI_MARKER in (expense.notes or ''): continue
        if limit is not None and processed >= limit: break
        processed += 1
        try:
            if process_expense(expense, actor_id=actor_id): changed += 1
        except Exception:
            db.session.rollback(); current_app.logger.exception('Falha ao reprocessar nota da despesa %s', expense.id)
    return processed, changed


def init_receipt_ai_upgrade(app):
    @app.before_request
    def _capture_latest_expense_id():
        if request.method == 'POST' and request.endpoint in {'main.maintenance_new', 'main.fuel_new'} and current_user.is_authenticated:
            latest = Expense.query.filter_by(created_by_id=current_user.id).order_by(Expense.id.desc()).first()
            g._receipt_ai_previous_expense_id = latest.id if latest else 0

    @app.after_request
    def _sync_new_receipt(response):
        if response.status_code < 400 and request.method == 'POST' and request.endpoint in {'main.maintenance_new', 'main.fuel_new'} and current_user.is_authenticated and (os.getenv('OPENAI_API_KEY') or '').strip():
            previous = getattr(g, '_receipt_ai_previous_expense_id', 0)
            latest = Expense.query.filter(Expense.created_by_id == current_user.id, Expense.id > previous).order_by(Expense.id.desc()).first()
            if latest:
                try: process_expense(latest, actor_id=current_user.id)
                except Exception:
                    db.session.rollback(); current_app.logger.exception('Falha na análise automática da nova nota %s', latest.id)
        return response

    @app.post('/admin/despesas/<int:expense_id>/analisar-ia')
    def analyze_expense_manually(expense_id):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Apenas administradores podem analisar notas antigas com IA.', 'error')
            return redirect(url_for('main.history'))
        expense = Expense.query.get_or_404(expense_id)
        if expense.asset_type != 'MOTORCYCLE':
            flash('A análise por IA está habilitada para motos.', 'error')
            return redirect(request.referrer or url_for('main.history'))
        if not (os.getenv('OPENAI_API_KEY') or '').strip():
            flash('OPENAI_API_KEY não está configurada.', 'error')
            return redirect(request.referrer or url_for('main.history'))
        try:
            changed = process_expense(expense, actor_id=current_user.id, force=False)
            if changed: flash('Nota analisada pela IA e ficha da moto atualizada.', 'success')
            elif AI_MARKER in (expense.notes or ''): flash('Esta nota já foi analisada pela IA.', 'info')
            else: flash('Não foi possível analisar: confira se a nota/comprovante está anexado.', 'error')
        except Exception as exc:
            db.session.rollback(); current_app.logger.exception('Falha na análise manual da nota %s', expense_id)
            flash(f'Falha ao analisar a nota com IA: {str(exc)[:180]}', 'error')
        return redirect(request.referrer or url_for('main.history'))

    @app.cli.command('reprocessar-notas-ia')
    def reprocessar_notas_ia():
        if not (os.getenv('OPENAI_API_KEY') or '').strip():
            print('OPENAI_API_KEY não configurada; nenhuma nota foi processada.'); return
        processed, changed = reprocess_existing(actor_id=None)
        print(f'Notas verificadas: {processed}; fichas atualizadas: {changed}.')
