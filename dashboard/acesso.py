"""Autorizacao de leitura integral para lista explicita de usuarios OIDC."""

import math
import time


def previa_local_permitida(solicitada, endereco, modo_demo):
    return solicitada and not modo_demo and endereco in ('127.0.0.1', '::1')


def usuario_permitido(usuario, emails):
    email = str(usuario.get('email', '')).strip().casefold()
    permitidos = {str(item).strip().casefold() for item in emails}
    expiracao = usuario.get('exp')
    token_vigente = (isinstance(expiracao, (int, float)) and not isinstance(expiracao, bool)
                    and math.isfinite(expiracao) and expiracao > time.time())
    return token_vigente and usuario.get('email_verified') is True and bool(email) and email in permitidos
