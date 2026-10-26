#!/usr/bin/env python3
"""Publica PNG com texto opcional no X com OAuth 1.0a e biblioteca padrão."""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KEYS = ('X_CONSUMER_KEY', 'X_CONSUMER_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_TOKEN_SECRET')
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def quote(value):
    return urllib.parse.quote(str(value), safe='~-._')


def load_credentials(filename):
    values = {key: os.environ.get(key, '') for key in KEYS}
    if not all(values.values()):
        try:
            with open(filename, encoding='utf-8') as source:
                for line in source:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, value = line.split('=', 1)
                    key, value = key.strip(), value.strip()
                    if key in KEYS and not values[key]:
                        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                            value = value[1:-1]
                        values[key] = value
        except FileNotFoundError:
            pass
        except (OSError, UnicodeError):
            raise ValueError('Não foi possível ler o arquivo de credenciais.') from None
    missing = [key for key in KEYS if not values[key]]
    if missing:
        raise ValueError('Credenciais ausentes: ' + ', '.join(missing))
    return values


def authorization(method, url, credentials):
    oauth = {
        'oauth_consumer_key': credentials[KEYS[0]],
        'oauth_token': credentials[KEYS[2]],
        'oauth_nonce': secrets.token_hex(16),
        'oauth_timestamp': str(int(time.time())),
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_version': '1.0',
    }
    parts = urllib.parse.urlsplit(url)
    parameters = urllib.parse.parse_qsl(parts.query, keep_blank_values=True) + list(oauth.items())
    normalized = '&'.join(k + '=' + v for k, v in sorted((quote(k), quote(v)) for k, v in parameters))
    base_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path or '/', '', ''))
    base = '&'.join(quote(item) for item in (method.upper(), base_url, normalized))
    key = quote(credentials[KEYS[1]]) + '&' + quote(credentials[KEYS[3]])
    oauth['oauth_signature'] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return 'OAuth ' + ', '.join(quote(k) + '="' + quote(v) + '"' for k, v in sorted(oauth.items()))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(method, url, credentials, body=None, content_type=None):
    headers = {'Authorization': authorization(method, url, credentials), 'Accept': 'application/json'}
    if content_type:
        headers['Content-Type'] = content_type
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
        return json.load(response)


def text_length(text):
    # Aproximação: URLs valem 23; demais caracteres contam por code point.
    return len(re.sub(r'https?://[^\s]+', lambda match: 'x' * 23, text, flags=re.IGNORECASE))


def multipart(image):
    boundary = 'xpost-' + secrets.token_hex(24)
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="media_category"\r\n\r\ntweet_image\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="media"; filename="image.png"\r\n'
        'Content-Type: image/png\r\n\r\n'
    ).encode() + image + f'\r\n--{boundary}--\r\n'.encode()
    return body, 'multipart/form-data; boundary=' + boundary


def redact(message, credentials):
    for value in sorted(set(credentials.values()), key=len, reverse=True):
        if value:
            for variant in {value, quote(value), urllib.parse.quote_plus(value), json.dumps(value, ensure_ascii=True)[1:-1]}:
                message = message.replace(variant, '[REDACTED]')
    return message


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text', default='', help=r'Texto; a sequência literal \n vira quebra de linha.')
    parser.add_argument('--alt-text', help=r'Texto alternativo (até 1000 caracteres); \n vira quebra de linha.')
    parser.add_argument('--image', required=True, help='Caminho de um PNG de até 5 MiB.')
    parser.add_argument('--env-file', default=os.environ.get('X_ENV_FILE') or str(Path(__file__).resolve().parent / '.env'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Somente valida e consulta o usuário (padrão).')
    mode.add_argument('--publish', action='store_true', help='Envia a imagem e publica o post.')
    args = parser.parse_args(argv)
    credentials = {key: os.environ.get(key, '') for key in KEYS}
    try:
        text = args.text.replace('\\n', '\n')
        length = text_length(text)
        if not text.strip():
            text = ''
            length = 0
        if length > 280:
            raise ValueError('O texto deve ter até 280 caracteres pela contagem aproximada.')
        alt_text = args.alt_text.replace('\\n', '\n') if args.alt_text is not None else None
        alt_text_ok = None
        if alt_text is None or not alt_text.strip():
            raise ValueError('Texto alternativo não vazio é obrigatório.')
        if len(alt_text) > 1000:
            raise ValueError('O texto alternativo deve ter até 1000 caracteres.')
        payload = {'media': {'media_ids': ['<media_id>']}}
        if text:
            payload['text'] = text
        path = Path(args.image)
        try:
            with path.open('rb') as source:
                image = source.read(MAX_IMAGE_BYTES + 1)
        except OSError:
            raise ValueError('Não foi possível ler o arquivo PNG.') from None
        if len(image) > MAX_IMAGE_BYTES:
            raise ValueError('O PNG excede 5 MiB (5.242.880 bytes).')
        if not image.startswith(PNG_SIGNATURE):
            raise ValueError('Assinatura PNG inválida.')
        credentials = load_credentials(args.env_file)
        result = request_json('GET', 'https://api.x.com/2/users/me?user.fields=username,name', credentials)
        user = {key: result['data'][key] for key in ('id', 'username', 'name')}
        if not args.publish:
            output = {'mode': 'dry-run', 'ok': True, 'user': user, 'text': text, 'text_length': length,
                      'image': {'path': str(path), 'bytes': len(image)}, 'would_publish': False,
                      'payload': payload, 'alt_text': alt_text, 'alt_text_ok': alt_text_ok,
                      'image_only': not bool(text)}
        else:
            body, content_type = multipart(image)
            uploaded = request_json('POST', 'https://api.x.com/2/media/upload', credentials, body, content_type)
            data = uploaded.get('data', {})
            media_id = (data.get('id') if isinstance(data, dict) else None) or uploaded.get('id') or uploaded.get('media_id_string')
            if not media_id:
                raise ValueError('Resposta do upload sem identificador de mídia.')
            media_id = str(media_id)
            metadata = {'id': media_id, 'metadata': {'alt_text': {'text': alt_text}}}
            request_json('POST', 'https://api.x.com/2/media/metadata', credentials,
                         json.dumps(metadata).encode(), 'application/json')
            alt_text_ok = True
            payload['media']['media_ids'] = [media_id]
            body = json.dumps(payload).encode()
            posted = request_json('POST', 'https://api.x.com/2/tweets', credentials, body, 'application/json')
            post_id = posted['data']['id']
            output = {'mode': 'publish', 'id': post_id, 'url': f'https://x.com/{user["username"]}/status/{post_id}',
                      'payload': payload, 'alt_text': alt_text, 'alt_text_ok': alt_text_ok,
                      'image_only': not bool(text)}
        print(redact(json.dumps(output, ensure_ascii=False), credentials))
        return 0
    except urllib.error.HTTPError as error:
        body = error.read().decode('utf-8', errors='replace')
        output = {'error': 'HTTP error', 'status': error.code, 'body': redact(body, credentials)}
    except (urllib.error.URLError, TimeoutError, OSError):
        output = {'error': 'Falha de rede ou de entrada/saída.'}
    except ValueError as error:
        output = {'error': redact(str(error), credentials)}
    except (KeyError, TypeError):
        output = {'error': 'Resposta da API em formato inesperado.'}
    print(redact(json.dumps(output, ensure_ascii=False), credentials), file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
