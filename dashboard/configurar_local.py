"""Preparo exclusivo da credencial local; nunca reutiliza senha do pipeline."""

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess


RAIZ = Path(__file__).resolve().parents[1]
CONFIG_LOCAL = RAIZ / '.streamlit/bi.local.json'


def proteger_arquivo(caminho):
    if os.name == 'nt':
        identidade = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True)
        sid = identidade.strip().split(',')[-1].strip('"')
        subprocess.run(['icacls', str(caminho), '/inheritance:r', '/grant:r',
                        f'*{sid}:F', '*S-1-5-18:F'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        caminho.chmod(0o600)


def verificador_scram(senha):
    sal = secrets.token_bytes(16)
    derivada = hashlib.pbkdf2_hmac('sha256', senha.encode(), sal, 4096)
    cliente = hmac.digest(derivada, b'Client Key', 'sha256')
    armazenada = hashlib.sha256(cliente).digest()
    servidor = hmac.digest(derivada, b'Server Key', 'sha256')
    codificar = lambda valor: base64.b64encode(valor).decode('ascii')
    return f'SCRAM-SHA-256$4096:{codificar(sal)}${codificar(armazenada)}:{codificar(servidor)}'


def preparar_credencial():
    if CONFIG_LOCAL.exists():
        raise ValueError('Credencial local ja existe; nao sobrescrever ou rotacionar automaticamente.')
    permitidas = {'XFIT_PG_HOST', 'XFIT_PG_DATABASE', 'XFIT_PG_USER', 'XFIT_PG_SSLROOTCERT'}
    origem = {}
    for linha in (RAIZ / '.env').read_text(encoding='utf-8').splitlines():
        chave, separador, valor = linha.partition('=')
        if separador and chave.strip() in permitidas:
            origem[chave.strip()] = valor.strip().strip('"').strip("'")
    if set(origem) != permitidas or '.' not in origem['XFIT_PG_USER']:
        raise ValueError('Host, database, projeto e CA precisam estar configurados.')
    certificado = (RAIZ / origem['XFIT_PG_SSLROOTCERT']).resolve()
    if not certificado.is_file():
        raise ValueError('CA oficial nao encontrada.')
    senha = secrets.token_urlsafe(48)
    config = {
        'XFIT_BI_PG_HOST': origem['XFIT_PG_HOST'],
        'XFIT_BI_PG_DATABASE': origem['XFIT_PG_DATABASE'],
        'XFIT_BI_PG_USER': 'xfit_dashboard_app.' + origem['XFIT_PG_USER'].split('.', 1)[1],
        'XFIT_BI_PG_PASSWORD': senha,
        'XFIT_BI_PG_SSLROOTCERT': str(certificado),
    }
    with CONFIG_LOCAL.open('x', encoding='utf-8') as arquivo:
        proteger_arquivo(CONFIG_LOCAL)
        json.dump(config, arquivo, indent=2)
    return verificador_scram(senha)
