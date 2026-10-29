"""Previa com DW real, exclusivamente em loopback e sem configuracao de deploy."""

import json
import os
import subprocess
import sys

from dashboard.configurar_local import CONFIG_LOCAL, RAIZ


def executar():
    config = json.loads(CONFIG_LOCAL.read_text(encoding='utf-8'))
    ambiente = os.environ.copy()
    ambiente.update(config)
    ambiente.update(XFIT_DASHBOARD_DEMO='0', XFIT_DASHBOARD_LOCAL_DW='1')
    comando = [sys.executable, '-m', 'streamlit', 'run', 'dashboard/app.py',
               '--server.address=127.0.0.1', '--server.port=8502',
               '--server.headless=true', '--server.fileWatcherType=none']
    return subprocess.call(comando, cwd=RAIZ, env=ambiente)


if __name__ == '__main__':
    raise SystemExit(executar())
