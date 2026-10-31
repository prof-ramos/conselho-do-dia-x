#!/usr/bin/env python3
"""Gera e publica um conselho por dia, com dry-run como padrão."""
import argparse
import fcntl
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import secrets
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
AUTHOR = 'H. Jackson Brown, Jr.'
SOURCE = 'Pequeno Manual de Instruções para a Vida'


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, delete=False) as target:
            temporary = Path(target.name)
            json.dump(value, target, ensure_ascii=False, indent=2)
            target.write('\n')
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def safe_error(message):
    credentials = {value for key, value in os.environ.items() if value and
                   any(part in key.upper() for part in
                       ('SECRET', 'TOKEN', 'PASSWORD', 'API_KEY', 'CONSUMER_KEY', 'PRIVATE_KEY'))}
    for secret in sorted(credentials, key=len, reverse=True):
        message = message.replace(secret, '[REDACTED]')
    return message[:2000]


def render_failure(report):
    details = {key: report[key] for key in ('error', 'ocr_text', 'palavras_faltantes')
               if key in report}
    details['validacoes_reprovadas'] = [key for key in
        ('overflow_ok', 'ocr_ok', 'aspect_ok', 'size_ok', 'safe_area_ok', 'font_ok')
        if report.get(key) is False]
    return safe_error('Renderização falhou: ' + json.dumps(details, ensure_ascii=False))


def run_json(script, arguments):
    result = subprocess.run([sys.executable, str(ROOT / script), *arguments],
                            capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
    if script == 'render.py':
        try:
            report = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            report = None
        if isinstance(report, dict) and (result.returncode or report.get('error')):
            raise ValueError(render_failure(report))
    # Não repassar stdout/stderr dos filhos: podem conter dados sensíveis.
    if result.returncode:
        for line in reversed(result.stderr.splitlines()):
            try:
                failure = json.loads(line)
            except ValueError:
                continue
            diagnostic = {}
            if isinstance(failure, dict):
                credentials = sorted({os.environ[key] for key in (
                    'X_CONSUMER_KEY', 'X_CONSUMER_SECRET',
                    'X_ACCESS_TOKEN', 'X_ACCESS_TOKEN_SECRET') if os.environ.get(key)},
                    key=len, reverse=True)

                def safe_text(value):
                    for secret in credentials:
                        value = value.replace(secret, '[REDACTED]')
                    return value[:200]

                if failure.get('stage') in ('validation', 'user_lookup', 'media_upload', 'media_metadata', 'post_create'):
                    diagnostic['stage'] = failure['stage']
                if isinstance(failure.get('error'), str):
                    diagnostic['error'] = safe_text(failure['error'])
                if type(failure.get('status')) in (int, float):
                    status = failure['status']
                    # Credenciais também não devem aparecer em valores numéricos.
                    if all(secret not in str(status) for secret in credentials):
                        if status == status and abs(status) != float('inf'):
                            diagnostic['status'] = status
                body = failure.get('body')
                if isinstance(body, str):
                    try:
                        body = json.loads(body)
                    except ValueError:
                        body = None
                if isinstance(body, dict):
                    diagnostic['body'] = {key: safe_text(body[key])
                                          for key in ('title', 'detail', 'type')
                                          if isinstance(body.get(key), str)}
            print(f'diagnostico {script}: ' + json.dumps(diagnostic, ensure_ascii=False),
                  file=sys.stderr)
            break
        raise ValueError(f'{script} falhou (código {result.returncode}).')
    try:
        value = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise ValueError(f'{script} não retornou JSON válido.') from None
    if not isinstance(value, dict) or value.get('error') or value.get('ok') is False:
        raise ValueError(f'{script} retornou uma resposta de falha.')
    return value


def pending_path(state_path):
    return state_path.with_name('publication.pending.json')


def prepare(state_path, n, today):
    intent = {'attempt': secrets.token_hex(16), 'n': n, 'data': today, 'status': 'prepared'}
    # Exclusive creation: a previous attempt must be reconciled, never overwritten.
    with pending_path(state_path).open('x', encoding='utf-8') as target:
        json.dump(intent, target, ensure_ascii=False)
        target.write('\n')
        target.flush()
        os.fsync(target.fileno())
    sync_directory(state_path.parent)
    return intent


def finish_publication(state_path, state, receipt):
    n = receipt['n']
    if (receipt.get('status') != 'confirmed' or not receipt.get('id') or not receipt.get('url')
            or type(n) is not int or not isinstance(receipt.get('data'), str)):
        raise ValueError('Tentativa sem recibo confirmado; conferir o X antes de repetir.')
    if state.get('proximo') not in (n, n + 1):
        raise ValueError('Recibo incompatível com o estado atual.')
    log_path = state_path.with_name('log.jsonl')
    records = [json.loads(line) for line in log_path.read_text(encoding='utf-8').splitlines()
               if line.strip()] if log_path.exists() else []
    existing = [record for record in records if record.get('n') == n]
    if existing and any(record.get('id') != receipt['id'] for record in existing):
        raise ValueError('Registro divergente; conferir o X antes de reconciliar.')
    if not existing:
        with log_path.open('a', encoding='utf-8') as log:
            log.write(json.dumps({key: receipt[key] for key in ('n', 'id', 'url', 'data')},
                                 ensure_ascii=False) + '\n')
            log.flush()
            os.fsync(log.fileno())
    state.update(proximo=n + 1, ultimo_enviado=n, data_ultimo_envio=receipt['data'])
    atomic_json(state_path, state)
    pending_path(state_path).unlink()  # State and log are already durable.
    sync_directory(state_path.parent)


def execute(args):
    published = False
    try:
        today = datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat()
        if not args.estado.exists():
            shutil.copyfile(ROOT / 'estado.example.json', args.estado)
        state = json.loads(args.estado.read_text(encoding='utf-8'))
        if not isinstance(state, dict):
            raise ValueError('Estado deve ser um objeto JSON.')
        pending = pending_path(args.estado)
        if args.recover:
            receipt = json.loads(pending.read_text(encoding='utf-8'))
            finish_publication(args.estado, state, receipt)
            print(json.dumps({'ok': True, 'mode': 'recover', 'id': receipt['id'],
                              'url': receipt['url'], 'n': receipt['n']}))
            return 0
        if (args.publish or args.prepare) and pending.exists() and not args.prepared_attempt:
            raise ValueError('Tentativa pendente; conferir o X e reconciliar antes de repetir.')
        if (args.publish or args.prepare) and state.get('data_ultimo_envio') == today:
            print(json.dumps({'ok': True, 'mode': 'publish', 'skipped': True,
                              'reason': 'Já publicado hoje.', 'data': today}, ensure_ascii=False))
            return 0
        n = state.get('proximo')
        if type(n) is not int or n < 1:
            raise ValueError('Estado contém proximo inválido.')
        entries = json.loads(args.conselhos.read_text(encoding='utf-8'))
        matches = [item for item in entries if isinstance(item, dict) and item.get('n') == n]
        if len(matches) != 1 or not isinstance(matches[0].get('text'), str) or not matches[0]['text'].strip():
            raise ValueError('Conselho ausente, duplicado ou inválido para proximo.')
        if args.prepare:
            intent = prepare(args.estado, n, today)
            print(json.dumps({'ok': True, 'mode': 'prepare', **intent}))
            return 0
        intent = None
        if args.publish:
            if args.prepared_attempt:
                intent = json.loads(pending.read_text(encoding='utf-8'))
                if (intent.get('attempt') != args.prepared_attempt or intent.get('n') != n
                        or intent.get('data') != today or intent.get('status') != 'prepared'):
                    raise ValueError('Tentativa preparada incompatível ou já iniciada.')
            else:
                intent = prepare(args.estado, n, today)
        text = matches[0]['text']
        rendered = run_json('render.py', ['--text', f'{n}. {text}', '--author', AUTHOR,
                            '--source', SOURCE, '--n', str(n), '--url', args.url])
        image_fields = ('width', 'height', 'bytes', 'overflow_ok', 'ocr_ok',
                        'aspect_ok', 'size_ok', 'safe_area_ok', 'font_ok')
        if (any(rendered.get(key) is not True for key in image_fields[3:])
                or not isinstance(rendered.get('path'), str)):
            raise ValueError(render_failure(rendered))
        alt_text = f'{n}. {text}\n{AUTHOR}\n{SOURCE}'
        if args.publish:
            intent['status'] = 'sending'
            atomic_json(pending, intent)
        posted = run_json('post.py', ['--alt-text', alt_text, '--image', rendered['path'],
                                    '--publish' if args.publish else '--dry-run'])
        if args.publish:
            published = bool(posted.get('id') and posted.get('url'))
            if not published:
                raise ValueError('Publicação sem id ou URL; confira o X antes de repetir.')
            intent.update(status='confirmed', id=posted['id'], url=posted['url'])
            atomic_json(pending, intent)  # Receipt survives state/log failures.
        payload = posted.get('payload')
        image_only_ok = (isinstance(payload, dict) and 'text' not in payload
                         and isinstance(payload.get('media'), dict)
                         and isinstance(payload['media'].get('media_ids'), list)
                         and bool(payload['media']['media_ids'])
                         and all(payload['media']['media_ids']))
        if not image_only_ok or (args.publish and posted.get('alt_text_ok') is not True):
            raise ValueError('Publicação deve conter somente mídia e texto alternativo confirmado.')
        if args.publish:
            finish_publication(args.estado, state, intent)
        summary = {'ok': True, 'mode': 'publish' if args.publish else 'dry-run',
                   'n': n, 'image': rendered['path'], 'data': today,
                   'estado_atualizado': args.publish,
                   'image_only_ok': image_only_ok, 'alt_text': posted.get('alt_text')}
        summary.update({key: rendered.get(key) for key in image_fields})
        if args.publish:
            summary.update(id=posted['id'], url=posted['url'], alt_text_ok=posted['alt_text_ok'])
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({'ok': False,
                          'error': safe_error(str(exc)) + ' Se houver publication.pending.json, conferir o X antes de repetir.',
                          'publicacao_confirmada': published}, ensure_ascii=False), file=sys.stderr)
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--estado', type=Path, default=ROOT / 'estado.json')
    parser.add_argument('--conselhos', type=Path, default=ROOT / 'conselhos.json')
    parser.add_argument('--url', default='http://127.0.0.1:5173')
    parser.add_argument('--prepared-attempt', help='ID preparado e persistido antes desta execução.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--publish', action='store_true')
    mode.add_argument('--prepare', action='store_true', help='Registra intenção sem acessar o X.')
    mode.add_argument('--recover', action='store_true', help='Reconcilia recibo confirmado sem publicar.')
    args = parser.parse_args(argv)
    if args.prepared_attempt and not args.publish:
        parser.error('--prepared-attempt exige --publish')
    if not (args.publish or args.prepare or args.recover):
        return execute(args)
    # Stable lock file, never unlinked: serializes local processes on Linux/macOS.
    with args.estado.with_name('.publication.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'ok': False, 'error': 'Outra rotina de publicação está em execução.'}), file=sys.stderr)
            return 1
        return execute(args)


if __name__ == '__main__':
    sys.exit(main())
