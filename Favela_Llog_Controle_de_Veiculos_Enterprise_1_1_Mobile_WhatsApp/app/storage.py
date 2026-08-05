import os
from dataclasses import dataclass
from urllib.parse import quote

import requests
from flask import current_app


@dataclass
class StorageResult:
    bucket: str
    path: str


class SupabaseStorageError(RuntimeError):
    pass


def _settings():
    url = (os.getenv('SUPABASE_URL') or '').rstrip('/')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or ''
    bucket = os.getenv('SUPABASE_STORAGE_BUCKET') or 'controle-veiculos'
    return url, key, bucket


def is_configured():
    url, key, _ = _settings()
    return bool(url and key)


def _headers(content_type=None):
    _, key, _ = _settings()
    headers = {
        'Authorization': f'Bearer {key}',
        'apikey': key,
    }
    if content_type:
        headers['Content-Type'] = content_type
    return headers


def ensure_bucket():
    url, _, bucket = _settings()
    if not is_configured():
        raise SupabaseStorageError('Supabase Storage não configurado no Render.')
    endpoint = f'{url}/storage/v1/bucket'
    response = requests.get(endpoint, headers=_headers(), timeout=30)
    if response.status_code >= 400:
        raise SupabaseStorageError(f'Falha ao consultar buckets: {response.text[:300]}')
    buckets = response.json() if response.content else []
    if any(item.get('name') == bucket or item.get('id') == bucket for item in buckets):
        return bucket
    response = requests.post(endpoint, headers=_headers('application/json'), json={
        'id': bucket,
        'name': bucket,
        'public': False,
        'file_size_limit': current_app.config.get('MAX_CONTENT_LENGTH', 8 * 1024 * 1024),
        'allowed_mime_types': ['image/jpeg','image/png','image/webp','application/pdf'],
    }, timeout=30)
    if response.status_code not in (200, 201):
        raise SupabaseStorageError(f'Falha ao criar bucket: {response.text[:300]}')
    return bucket


def upload_bytes(path, data, mime_type, upsert=False):
    url, _, bucket = _settings()
    ensure_bucket()
    encoded = quote(path, safe='/')
    endpoint = f'{url}/storage/v1/object/{bucket}/{encoded}'
    headers = _headers(mime_type or 'application/octet-stream')
    headers['x-upsert'] = 'true' if upsert else 'false'
    response = requests.post(endpoint, headers=headers, data=data, timeout=90)
    if response.status_code not in (200, 201):
        raise SupabaseStorageError(f'Falha no upload: {response.text[:400]}')
    return StorageResult(bucket=bucket, path=path)


def download_bytes(bucket, path):
    url, _, default_bucket = _settings()
    bucket = bucket or default_bucket
    if not is_configured():
        raise SupabaseStorageError('Supabase Storage não configurado.')
    encoded = quote(path, safe='/')
    endpoint = f'{url}/storage/v1/object/authenticated/{bucket}/{encoded}'
    response = requests.get(endpoint, headers=_headers(), timeout=90)
    if response.status_code != 200:
        raise SupabaseStorageError(f'Arquivo não disponível no Storage: {response.text[:300]}')
    return response.content, response.headers.get('Content-Type')
