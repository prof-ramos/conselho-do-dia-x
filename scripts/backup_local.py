#!/usr/bin/env python3
"""Backup local da publicação; --check não altera o repositório."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SERIF = Path('/home/box/repos/serif-sh')
COMMIT = 'abc59e082e476385326f7a7e840f08965f9e6f00'
OP = '/home/box/.local/bin/op'
MAPPING = {'consumer_key': 'X_CONSUMER_KEY', 'consumer_secret': 'X_CONSUMER_SECRET',
           'access_token': 'X_ACCESS_TOKEN', 'access_token_secret': 'X_ACCESS_TOKEN_SECRET'}


class Failure(Exception):
    pass


def run(args, *, env=None, cwd=ROOT):
    if env is None:
        env = {key: value for key, value in os.environ.items() if key not in MAPPING.values()}
    try:
        return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        raise Failure('não foi possível executar ' + Path(args[0]).name) from None


def checked(args, message, **kwargs):
    result = run(args, **kwargs)
    if result.returncode:
        raise Failure(message)
    return result.stdout


def guards():
    if (ROOT / 'publication.pending.json').exists():
        raise Failure('existe publication.pending.json; reconcilie a tentativa antes de continuar')
    try:
        state = json.loads((ROOT / 'estado.json').read_text(encoding='utf-8'))
        if not isinstance(state, dict):
            raise ValueError()
    except (OSError, ValueError):
        raise Failure('não foi possível ler estado.json') from None
    if state.get('data_ultimo_envio') == datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat():
        raise Failure('o conselho de hoje já consta em estado.json')


def credentials():
    raw = checked([OP, 'item', 'get', 'h2kp6shxleghbt4zbxy4vu6kwa', '--vault', 'Bots', '--format', 'json'],
                  'falha ao obter credenciais no 1Password')
    try:
        fields = json.loads(raw)['fields']
        values = {MAPPING[f['label']]: f['value'] for f in fields
                  if f.get('label') in MAPPING and f.get('value')}
    except (ValueError, KeyError, TypeError):
        raise Failure('resposta inválida do 1Password') from None
    if set(values) != set(MAPPING.values()) or not all(isinstance(v, str) for v in values.values()):
        raise Failure('faltam credenciais do X no 1Password')
    env = os.environ.copy()
    env.update(values)
    return env


def preflight():
    try:
        with urlopen('http://127.0.0.1:5173/', timeout=3) as response:
            if response.status != 200:
                raise Failure('serif-sh não respondeu HTTP 200')
    except (OSError, URLError):
        raise Failure('serif-sh não está acessível em 127.0.0.1:5173') from None
    head = checked(['git', '-C', str(SERIF), 'rev-parse', 'HEAD'], 'não foi possível verificar o commit do serif-sh').strip()
    if head != COMMIT:
        raise Failure('serif-sh está no commit incorreto')
    branch = checked(['git', 'branch', '--show-current'], 'não foi possível verificar a branch').strip()
    if branch != 'main':
        raise Failure('o repositório precisa estar na branch main')
    guards()


def execute(check=False):
    preflight()
    if not check:
        checked(['git', 'pull', '--ff-only', 'origin', 'main'], 'git pull falhou')
        guards()
    env = credentials()
    if check:
        return 'Verificações concluídas; nenhuma publicação realizada.'
    checked([sys.executable, 'daily.py', '--dry-run'], 'dry-run falhou', env=env)
    raw = checked([sys.executable, 'daily.py', '--prepare'], 'preparação falhou')
    try:
        preparation = json.loads(raw)
        attempt = preparation['attempt']
        if preparation.get('ok') is not True or not isinstance(attempt, str) or not attempt:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise Failure('resposta inválida da preparação; verifique a pendência') from None
    checked([sys.executable, 'ci_state.py', 'preparar tentativa de publicacao'],
            'falha ao persistir preparação; não publique novamente')
    published = None
    try:
        published = run([sys.executable, 'daily.py', '--publish', '--prepared-attempt', attempt], env=env)
    finally:
        persist = run([sys.executable, 'ci_state.py', 'persistir resultado da tentativa'])
    if persist.returncode:
        raise Failure('falha ao persistir resultado; reconcilie a tentativa antes de repetir')
    if published.returncode:
        raise Failure('publicação falhou; resultado persistido, reconcilie antes de repetir')
    try:
        summary = json.loads(published.stdout)
        url = summary['url']
        if summary.get('ok') is not True or not isinstance(url, str) or not url.startswith('https://') or any(c.isspace() for c in url):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise Failure('resultado de publicação inválido; reconcilie antes de repetir') from None
    return url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='somente verificações, sem pull ou publicação')
    args = parser.parse_args()
    try:
        print(execute(args.check))
    except Failure as exc:
        print('Falha: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
