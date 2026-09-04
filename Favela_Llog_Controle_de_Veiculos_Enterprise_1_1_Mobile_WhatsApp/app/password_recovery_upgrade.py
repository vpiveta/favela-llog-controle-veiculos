import hmac
import os

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, logout_user

from .models import db, User, AuditLog


def forgot_password_v2():
    # Se o usuário chegou à recuperação já autenticado (por exemplo, preso no
    # primeiro acesso), encerra a sessão para permitir a recuperação normal.
    if current_user.is_authenticated and request.method == 'GET':
        logout_user()

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        verification = (request.form.get('verification') or '').strip()
        new_password = request.form.get('new_password') or ''
        confirm = request.form.get('confirm_password') or ''

        try:
            user = User.query.filter_by(username=username, active=True).first()
            if not user:
                raise ValueError('Não foi possível validar os dados informados.')

            if len(new_password) < 6:
                raise ValueError('A nova senha deve ter pelo menos 6 caracteres.')
            if new_password != confirm:
                raise ValueError('A confirmação da nova senha não confere.')

            if user.role == 'DRIVER':
                from .enterprise19_wait import DriverDocument
                cnh = ''.join(c for c in verification if c.isdigit())
                doc = DriverDocument.query.filter_by(user_id=user.id).first()
                if not doc or not hmac.compare_digest(doc.cnh_number or '', cnh):
                    raise ValueError('Usuário ou CNH não conferem.')
                recovery_method = 'CNH cadastrada'
            elif user.is_admin:
                recovery_code = os.getenv('ADMIN_RECOVERY_CODE') or ''
                if not recovery_code:
                    raise ValueError('A recuperação administrativa ainda não foi configurada. Defina ADMIN_RECOVERY_CODE no Render.')
                if not hmac.compare_digest(recovery_code, verification):
                    raise ValueError('Usuário ou código de recuperação não conferem.')
                recovery_method = 'código administrativo de recuperação'
            else:
                raise ValueError('Não foi possível validar os dados informados.')

            user.set_password(new_password)
            # Recuperação validada equivale à criação de uma senha pessoal.
            # Portanto, o usuário NÃO deve voltar para a tela de primeiro acesso.
            user.must_change_password = False
            db.session.add(AuditLog(
                action='RECOVER_PASSWORD',
                entity_type='USER',
                entity_id=user.id,
                description=f'Senha recuperada pelo próprio usuário usando {recovery_method}; primeiro acesso concluído.',
                base_code=user.base_code,
                user_id=user.id,
            ))
            db.session.commit()

            # Garante que uma sessão antiga não mantenha estado anterior em cache.
            if current_user.is_authenticated:
                logout_user()
            flash('Senha redefinida com sucesso. Entre com a nova senha.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), 'danger')

    return render_template('auth/forgot_password.html')


def init_password_recovery_upgrade(app):
    # Substitui somente a função da rota já existente, sem alterar a URL.
    app.view_functions['production.forgot_password'] = forgot_password_v2
