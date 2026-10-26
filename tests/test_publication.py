import contextlib
import fcntl
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import daily
import post


class PostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.image = Path(self.tmp.name) / 'image.png'
        self.image.write_bytes(post.PNG_SIGNATURE + b'fixture')
        self.calls = []

    def request(self, method, url, credentials, body=None, content_type=None):
        self.calls.append((url, json.loads(body) if content_type == 'application/json' else None))
        if '/users/me' in url:
            return {'data': {'id': '1', 'username': 'example', 'name': 'Example'}}
        if url.endswith('/upload'):
            return {'data': {'id': 'media-id'}}
        if url.endswith('/metadata') and self.metadata_fails:
            raise TimeoutError('fake-credential-secret')
        if url.endswith('/tweets'):
            return {'data': {'id': '123'}}
        return {}

    def run_post(self, *args, metadata_fails=False):
        self.metadata_fails = metadata_fails
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(post, 'load_credentials', return_value=dict.fromkeys(post.KEYS, 'fake-credential-secret')), \
                patch.object(post, 'request_json', side_effect=self.request), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = post.main(['--image', str(self.image), *args])
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_metadata_failure_prevents_post(self):
        rc, out, err = self.run_post('--publish', '--alt-text', 'Conselho', metadata_fails=True)
        self.assertEqual(rc, 1)
        self.assertFalse(any(url.endswith('/tweets') for url, _ in self.calls))
        self.assertNotIn('fake-credential-secret', out + err)

    def test_missing_or_blank_alt_prevents_network(self):
        for args in [[], ['--alt-text', '   ']]:
            with self.subTest(args=args):
                self.calls.clear()
                rc, _, _ = self.run_post('--publish', *args)
                self.assertEqual(rc, 1)
                self.assertEqual(self.calls, [])

    def test_success_is_image_only_with_alt(self):
        rc, out, _ = self.run_post('--publish', '--alt-text', 'Conselho\\nAutor')
        self.assertEqual(rc, 0)
        result = json.loads(out)
        self.assertTrue(result['alt_text_ok'])
        self.assertEqual(result['payload'], {'media': {'media_ids': ['media-id']}})
        metadata = next(body for url, body in self.calls if url.endswith('/metadata'))
        self.assertEqual(metadata['metadata']['alt_text']['text'], 'Conselho\nAutor')

    def test_dry_run_never_uploads(self):
        rc, out, _ = self.run_post('--dry-run', '--alt-text', 'Conselho')
        self.assertEqual(rc, 0)
        self.assertFalse(json.loads(out)['would_publish'])
        self.assertEqual(len(self.calls), 1)


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.addCleanup(patch.stopall)
        patch.object(daily, 'ROOT', self.root).start()
        self.state = self.root / 'estado.json'
        self.state.write_text(json.dumps({'proximo': 4, 'ultimo_enviado': 3, 'data_ultimo_envio': '2000-01-01'}))
        (self.root / 'conselhos.json').write_text(json.dumps([{'n': 4, 'text': 'Conselho quatro.'}, {'n': 5, 'text': 'Cinco.'}]))
        self.sends = []
        self.fail_post = False
        patch.object(daily, 'run_json', side_effect=self.child).start()

    def child(self, script, args):
        if script == 'render.py':
            return {'path': str(self.root / 'image.png'), 'width': 1600, 'height': 900, 'bytes': 100,
                    **dict.fromkeys(('overflow_ok', 'ocr_ok', 'aspect_ok', 'size_ok', 'safe_area_ok', 'font_ok'), True)}
        if '--publish' in args:
            self.sends.append(args)
            if self.fail_post:
                raise ValueError('simulated uncertain API response')
        return {'id': '123', 'url': 'https://x.com/example/status/123', 'alt_text_ok': True,
                'payload': {'media': {'media_ids': ['media-id']}}}

    def run_daily(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = daily.main(list(args))
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_timeout_leaves_barrier_and_retry_does_not_send(self):
        self.fail_post = True
        self.assertEqual(self.run_daily('--publish')[0], 1)
        self.assertTrue((self.root / 'publication.pending.json').exists())
        self.assertEqual(self.run_daily('--publish')[0], 1)
        self.assertEqual(len(self.sends), 1)

    def test_state_failure_after_post_keeps_receipt_and_blocks_retry(self):
        original = daily.atomic_json
        def write(path, value):
            if path == self.state:
                raise OSError('simulated disk failure')
            return original(path, value)
        with patch.object(daily, 'atomic_json', side_effect=write):
            self.assertEqual(self.run_daily('--publish')[0], 1)
        receipt = json.loads((self.root / 'publication.pending.json').read_text())
        self.assertEqual(receipt['id'], '123')
        self.assertEqual(self.run_daily('--publish')[0], 1)
        self.assertEqual(len(self.sends), 1)
        self.assertEqual(self.run_daily('--recover')[0], 0)
        self.assertEqual(json.loads(self.state.read_text())['proximo'], 5)
        self.assertEqual(len(self.sends), 1)

    def test_success_advances_once_and_same_day_skips(self):
        self.assertEqual(self.run_daily('--publish')[0], 0)
        self.assertEqual(json.loads(self.state.read_text())['proximo'], 5)
        self.assertEqual(json.loads((self.root / 'log.jsonl').read_text())['id'], '123')
        self.assertFalse((self.root / 'publication.pending.json').exists())
        rc, out, _ = self.run_daily('--publish')
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(out)['skipped'])
        self.assertEqual(len(self.sends), 1)

    def test_preparation_blocks_new_attempt_until_matching_token(self):
        rc, out, _ = self.run_daily('--prepare')
        self.assertEqual(rc, 0)
        attempt = json.loads(out)['attempt']
        self.assertEqual(self.sends, [])
        self.assertEqual(self.run_daily('--prepare')[0], 1)
        self.assertEqual(self.run_daily('--publish')[0], 1)
        self.assertEqual(self.run_daily('--publish', '--prepared-attempt', 'wrong')[0], 1)
        self.assertEqual(self.run_daily('--publish', '--prepared-attempt', attempt)[0], 0)
        self.assertEqual(len(self.sends), 1)

    def test_uncertain_attempt_cannot_be_recovered_without_receipt(self):
        self.fail_post = True
        self.run_daily('--publish')
        self.assertEqual(self.run_daily('--recover')[0], 1)
        self.assertEqual(json.loads(self.state.read_text())['proximo'], 4)
        self.assertEqual(len(self.sends), 1)

    def test_started_attempt_cannot_be_reused_after_timeout(self):
        _, out, _ = self.run_daily('--prepare')
        attempt = json.loads(out)['attempt']
        self.fail_post = True
        self.assertEqual(self.run_daily('--publish', '--prepared-attempt', attempt)[0], 1)
        self.assertEqual(self.run_daily('--publish', '--prepared-attempt', attempt)[0], 1)
        self.assertEqual(len(self.sends), 1)

    def test_log_failure_keeps_receipt_until_recovery(self):
        log = self.root / 'log.jsonl'
        log.mkdir()  # A real filesystem error, before state is advanced.
        self.assertEqual(self.run_daily('--publish')[0], 1)
        self.assertEqual(json.loads(self.state.read_text())['proximo'], 4)
        self.assertTrue((self.root / 'publication.pending.json').exists())
        log.rmdir()
        self.assertEqual(self.run_daily('--recover')[0], 0)
        self.assertEqual(json.loads(self.state.read_text())['proximo'], 5)
        self.assertEqual(len(self.sends), 1)

    def test_recovery_does_not_duplicate_log_after_state_write_failure(self):
        original = daily.atomic_json
        def write(path, value):
            if path == self.state:
                raise OSError('disk failure')
            return original(path, value)
        with patch.object(daily, 'atomic_json', side_effect=write):
            self.run_daily('--publish')
        self.assertEqual(self.run_daily('--recover')[0], 0)
        lines = (self.root / 'log.jsonl').read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])['id'], '123')

    def test_receipt_write_failure_still_blocks_repetition(self):
        original = daily.atomic_json
        def write(path, value):
            if value.get('status') == 'confirmed':
                raise OSError('disk failure')
            return original(path, value)
        with patch.object(daily, 'atomic_json', side_effect=write):
            self.assertEqual(self.run_daily('--publish')[0], 1)
        self.assertEqual(self.run_daily('--publish')[0], 1)
        self.assertEqual(len(self.sends), 1)

    def test_local_concurrent_invocation_is_rejected(self):
        with (self.root / '.publication.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_daily('--publish')[0], 1)
        self.assertEqual(self.sends, [])

    def test_invalid_conselho_never_creates_attempt_or_sends(self):
        (self.root / 'conselhos.json').write_text('[]')
        self.assertEqual(self.run_daily('--publish')[0], 1)
        self.assertFalse((self.root / 'publication.pending.json').exists())
        self.assertEqual(self.sends, [])

    def test_dry_run_leaves_state_log_and_pending_untouched(self):
        before = self.state.read_bytes()
        self.assertEqual(self.run_daily('--dry-run')[0], 0)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertFalse((self.root / 'log.jsonl').exists())
        self.assertFalse((self.root / 'publication.pending.json').exists())
        self.assertEqual(self.sends, [])


if __name__ == '__main__':
    unittest.main()
