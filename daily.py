#!/usr/bin/env python3
"""Gera e publica um conselho por dia, com dry-run como padrão."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
AUTHOR = 'H. Jackson Brown, Jr.'
SOURCE = 'Pequeno Manual de Instruções para a Vida'


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
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_json(script, arguments):
    result = subprocess.run([sys.executable, str(ROOT / script), *arguments],
                            capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
    # Não repassar stdout/stderr dos filhos: podem conter dados sensíveis.
    if result.returncode:
        raise ValueError(f'{script} falhou (código {result.returncode}).')
    try:
        value = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise ValueError(f'{script} não retornou JSON válido.') from None
    if not isinstance(value, dict) or value.get('error') or value.get('ok') is False:
        raise ValueError(f'{script} retornou uma resposta de falha.')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--estado', type=Path, default=ROOT / 'estado.json')
    parser.add_argument('--conselhos', type=Path, default=ROOT / 'conselhos.json')
    parser.add_argument('--url', default='http://127.0.0.1:5173')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--publish', action='store_true')
    args = parser.parse_args(argv)
    published = False
    try:
        today = datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat()
        if not args.estado.exists():
            shutil.copyfile(ROOT / 'estado.example.json', args.estado)
        state = json.loads(args.estado.read_text(encoding='utf-8'))
        if not isinstance(state, dict):
            raise ValueError('Estado deve ser um objeto JSON.')
        if args.publish and state.get('data_ultimo_envio') == today:
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
        text = matches[0]['text']
        rendered = run_json('render.py', ['--text', text, '--author', AUTHOR,
                            '--source', SOURCE, '--n', str(n), '--url', args.url])
        if rendered.get('overflow_ok') is not True or rendered.get('ocr_ok') is not True or not isinstance(rendered.get('path'), str):
            raise ValueError('Renderização não passou nas validações de imagem.')
        post_text = f'{n}. {text}\n{AUTHOR}\n{SOURCE}'
        posted = run_json('post.py', ['--text', post_text, '--image', rendered['path'],
                                    '--publish' if args.publish else '--dry-run'])
        if args.publish:
            published = True
            if not posted.get('id') or not posted.get('url'):
                raise ValueError('Publicação sem id ou URL; confira o X antes de repetir.')
            state.update(proximo=n + 1, ultimo_enviado=n, data_ultimo_envio=today)
            atomic_json(args.estado, state)
            with (ROOT / 'log.jsonl').open('a', encoding='utf-8') as log:
                log.write(json.dumps({'n': n, 'id': posted['id'], 'url': posted['url'],
                                      'data': today}, ensure_ascii=False) + '\n')
        summary = {'ok': True, 'mode': 'publish' if args.publish else 'dry-run',
                   'n': n, 'image': rendered['path'], 'data': today,
                   'estado_atualizado': args.publish}
        if args.publish:
            summary.update(id=posted['id'], url=posted['url'])
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'ok': False, 'error': 'Falha ao processar estado, conselho ou subprocesso.',
                          'publicacao_confirmada': published}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
