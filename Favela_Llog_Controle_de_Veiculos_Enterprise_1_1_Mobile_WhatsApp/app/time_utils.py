import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = 'America/Sao_Paulo'


def app_timezone():
    """Retorna o fuso configurado, usando São Paulo como padrão operacional."""
    timezone_name = os.getenv('APP_TIMEZONE', DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        # Fallback seguro para instalações Windows sem base IANA disponível.
        return timezone(timedelta(hours=-3), name='America/Sao_Paulo')


def utc_now():
    """Mantém os timestamps no banco em UTC sem timezone, por compatibilidade."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_today():
    """Data operacional no fuso local, inclusive perto da virada do dia."""
    return datetime.now(app_timezone()).date()


def format_local_datetime(value, fmt='%d/%m/%Y %H:%M'):
    """Converte timestamps UTC do banco para o horário local na apresentação."""
    if value is None:
        return ''
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime(fmt)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(app_timezone()).strftime(fmt)
