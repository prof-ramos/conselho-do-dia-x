from collections import Counter
import json
import os
from unittest.mock import patch

import daily
from render import advice_words, missing_words


def test_ocr_ignores_misread_number():
    expected = Counter(advice_words('7. Olhe as pessoas nos olhos.'))
    for observed in ('z. Olhe as pessoas nos olhos.', '7. Olhe as pessoas nos olhos.',
                     'Olhe as pessoas nos olhos.'):
        assert missing_words(expected, observed) == []


def test_ocr_still_requires_all_content_words():
    expected = Counter(advice_words('7. Olhe as pessoas nos olhos.'))
    assert missing_words(expected, 'z. Olhe as pessoas nos.') == ['olhos']
    assert missing_words(Counter(advice_words('7. Vá, vá agora.')), 'z. Vá agora.') == ['va']
    assert advice_words('Olhe as pessoas nos olhos.') == ['olhe', 'as', 'pessoas', 'nos', 'olhos']


def test_render_error_propagates_and_redacts():
    report = {'error': 'OCR incompleto', 'ocr_ok': False,
              'ocr_text': 'z. Olhe test-secret', 'palavras_faltantes': ['olhos']}
    child = daily.subprocess.CompletedProcess([], 1, stdout=json.dumps(report), stderr='private')
    with patch.dict(os.environ, {'X_ACCESS_TOKEN': 'test-secret'}), \
            patch.object(daily.subprocess, 'run', return_value=child):
        try:
            daily.run_json('render.py', [])
        except ValueError as exc:
            message = str(exc)
        else:
            raise AssertionError('Expected render failure')
    assert 'OCR incompleto' in message
    assert 'z. Olhe' in message
    assert 'olhos' in message
    assert 'test-secret' not in message
    assert '[REDACTED]' in message
