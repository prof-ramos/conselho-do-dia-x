#!/usr/bin/env python3
"""Persiste somente o estado da publicação; falha de push impede o próximo passo."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
FILES = ('estado.json', 'log.jsonl', 'publication.pending.json')


def persist(message):
    for name in FILES:
        if (ROOT / name).exists():
            subprocess.run(['git', 'add', '-f', '--', name], cwd=ROOT, check=True)
        elif subprocess.run(['git', 'ls-files', '--error-unmatch', '--', name], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            subprocess.run(['git', 'add', '-u', '--', name], cwd=ROOT, check=True)
    diff = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT)
    if diff.returncode not in (0, 1):
        diff.check_returncode()
    if diff.returncode == 1:
        subprocess.run(['git', '-c', 'user.name=github-actions[bot]',
                        '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
                        'commit', '-m', '[skip ci] ' + message], cwd=ROOT, check=True)
    subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/main'], cwd=ROOT, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('message')
    persist(parser.parse_args().message)
