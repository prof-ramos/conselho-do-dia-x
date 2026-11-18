import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('backup_local', Path(__file__).resolve().parents[1] / 'scripts/backup_local.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'estado.json').write_text('{}')
        self.root_patch = patch.object(b, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.calls = []
        self.fail_publish = False
        self.fail_prepare_persist = False
        self.fields = [{'label': k, 'value': 'fake-' + k} for k in b.MAPPING]

    def run_mock(self, args, **kwargs):
        self.calls.append((args, kwargs))
        out = ''
        code = 0
        if args[0] == b.OP:
            out = json.dumps({'fields': self.fields})
        elif args[:2] == ['git', 'branch']:
            out = 'main\n'
        elif args[0] == 'git' and 'rev-parse' in args:
            out = b.COMMIT
        elif '--prepare' in args:
            out = json.dumps({'ok': True, 'attempt': 'attempt-1'})
        elif '--publish' in args:
            code = int(self.fail_publish)
            out = json.dumps({'ok': True, 'url': 'https://x.com/test/status/123'})
        elif 'preparar tentativa de publicacao' in args:
            code = int(self.fail_prepare_persist)
        return SimpleNamespace(returncode=code, stdout=out, stderr='fake-secret')

    def invoke(self, check=False):
        # Special methods are looked up on the type.
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(b.subprocess, 'run', side_effect=self.run_mock), patch.object(b, 'urlopen', return_value=Response()):
            return b.execute(check)

    def test_success_order_and_secret_environment(self):
        self.assertEqual(self.invoke(), 'https://x.com/test/status/123')
        commands = [args for args, _ in self.calls]
        self.assertEqual(sum('--publish' in c for c in commands), 1)
        self.assertLess(next(i for i,c in enumerate(commands) if '--dry-run' in c), next(i for i,c in enumerate(commands) if '--prepare' in c))
        self.assertLess(next(i for i,c in enumerate(commands) if 'preparar tentativa de publicacao' in c), next(i for i,c in enumerate(commands) if '--publish' in c))
        self.assertEqual(commands[-1][-1], 'persistir resultado da tentativa')
        for args, kwargs in self.calls:
            env = kwargs.get('env')
            if '--dry-run' in args or '--publish' in args:
                self.assertTrue(all(env[k].startswith('fake-') for k in b.MAPPING.values()))
            else:
                self.assertTrue(all(k not in env for k in b.MAPPING.values()))

    def test_publish_failure_still_persists(self):
        self.fail_publish = True
        with self.assertRaises(b.Failure): self.invoke()
        self.assertEqual(self.calls[-1][0][-1], 'persistir resultado da tentativa')
        self.assertEqual(sum('--publish' in c for c, _ in self.calls), 1)

    def test_preparation_persistence_failure_stops(self):
        self.fail_prepare_persist = True
        with self.assertRaises(b.Failure): self.invoke()
        self.assertFalse(any('--publish' in c for c, _ in self.calls))

    def test_check_does_not_mutate(self):
        self.invoke(True)
        self.assertFalse(any('pull' in c or '--prepare' in c or '--publish' in c or '--dry-run' in c for c, _ in self.calls))

    def test_pending_and_today_block(self):
        (self.root / 'publication.pending.json').touch()
        with self.assertRaises(b.Failure): self.invoke()
        (self.root / 'publication.pending.json').unlink()
        today = b.datetime.now(b.ZoneInfo('America/Sao_Paulo')).date().isoformat()
        (self.root / 'estado.json').write_text(json.dumps({'data_ultimo_envio': today}))
        with self.assertRaises(b.Failure): self.invoke()

    def test_missing_credentials_not_inherited(self):
        self.fields.pop()
        with patch.dict(b.os.environ, {'X_ACCESS_TOKEN_SECRET': 'ambient-fake'}):
            with self.assertRaises(b.Failure): self.invoke()

    def test_publish_launch_error_still_persists(self):
        original = self.run_mock
        def failing(args, **kwargs):
            if '--publish' in args:
                raise OSError('secret')
            return original(args, **kwargs)
        with patch.object(self, 'run_mock', side_effect=failing):
            with self.assertRaises(b.Failure): self.invoke()
        self.assertEqual(self.calls[-1][0][-1], 'persistir resultado da tentativa')


if __name__ == '__main__': unittest.main()
