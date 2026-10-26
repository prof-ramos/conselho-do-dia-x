import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ci_state


class DurablePreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.remote = root / 'remote.git'
        self.repo = root / 'repo'
        subprocess.run(['git', 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        subprocess.run(['git', 'init', '-b', 'main', str(self.repo)], check=True, capture_output=True)
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('remote', 'add', 'origin', str(self.remote))
        (self.repo / 'estado.json').write_text(json.dumps({'proximo': 4}))
        (self.repo / 'log.jsonl').touch()
        self.git('add', '.')
        self.git('commit', '-m', 'initial')
        self.git('push', 'origin', 'main')
        self.addCleanup(patch.stopall)
        patch.object(ci_state, 'ROOT', self.repo).start()

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def create_intent(self):
        pending = {'attempt': 'test-attempt', 'n': 4, 'data': '2000-01-01', 'status': 'prepared'}
        (self.repo / 'publication.pending.json').write_text(json.dumps(pending))
        return pending

    def test_prepared_attempt_is_exposed_only_after_remote_persistence(self):
        pending = self.create_intent()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ci_state.persist('Tentativa preparada')
        remote = subprocess.run(['git', '--git-dir', str(self.remote), 'show',
                                 'main:publication.pending.json'], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(remote.stdout), pending)

    def test_push_rejection_fails_and_remote_state_stays_intact(self):
        self.create_intent()
        hook = self.remote / 'hooks' / 'pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        with self.assertRaises(subprocess.CalledProcessError):
            ci_state.persist('Tentativa preparada')
        result = subprocess.run(['git', '--git-dir', str(self.remote), 'show',
                                 'main:publication.pending.json'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_final_push_failure_leaves_remote_barrier(self):
        self.create_intent()
        ci_state.persist('Tentativa preparada')
        (self.repo / 'publication.pending.json').unlink()
        (self.repo / 'estado.json').write_text(json.dumps({'proximo': 5}))
        hook = self.remote / 'hooks' / 'pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        with self.assertRaises(subprocess.CalledProcessError):
            ci_state.persist('Publicado')
        remote = subprocess.run(['git', '--git-dir', str(self.remote), 'show',
                                 'main:publication.pending.json'], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(remote.stdout)['n'], 4)


if __name__ == '__main__':
    unittest.main()
