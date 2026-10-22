#!/usr/bin/env python3
"""Renderiza o Editorial do serif.sh e valida DOM + OCR português."""
import argparse
import base64
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

ROOT = Path(__file__).resolve().parent
MAX_ATTEMPTS = 6
WIDTH, HEIGHT = 1600, 900
MAX_BYTES = 5 * 1024 * 1024
CHECKS = ('overflow_ok', 'ocr_ok', 'aspect_ok', 'size_ok', 'safe_area_ok')


def finalize_png(path, background):
    """Fit the entire export without cropping, then validate the saved PNG."""
    with Image.open(path) as original:
        fitted = ImageOps.contain(original.convert('RGBA'), (WIDTH, HEIGHT),
                                 Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (WIDTH, HEIGHT), tuple(background))
        canvas.alpha_composite(fitted, ((WIDTH - fitted.width) // 2,
                                      (HEIGHT - fitted.height) // 2))
        canvas.convert('RGB').save(path, format='PNG', optimize=True)
    with Image.open(path) as saved:
        width, height = saved.size
    size = path.stat().st_size
    return dict(width=width, height=height, bytes=size,
                aspect_ok=0.75 <= width / height <= 2.0 and
                          (width, height) == (WIDTH, HEIGHT),
                size_ok=size < MAX_BYTES)



def words(value):
    value = unicodedata.normalize('NFKD', value.lower())
    value = ''.join(c for c in value if not unicodedata.combining(c))
    # Punctuation, including typographic quotes, separates words.
    return re.findall(r'[^\W_]+', value, flags=re.UNICODE)


def ocr(path, expected):
    """Use one complete OCR reading; preserve word multiplicities."""
    best_missing = list(expected.elements())
    best_text = ''
    with Image.open(path) as original, tempfile.TemporaryDirectory() as tmp:
        gray = ImageOps.grayscale(original.convert('RGB'))
        gray = ImageOps.autocontrast(gray)
        gray = gray.resize((gray.width * 2, gray.height * 2), Image.Resampling.LANCZOS)
        prepared = Path(tmp) / 'ocr.png'
        gray.save(prepared)
        for psm in (6, 3, 11):
            result = subprocess.run(
                ['tesseract', str(prepared), 'stdout', '-l', 'por', '--psm', str(psm)],
                capture_output=True, text=True, check=True, timeout=90,
            )
            missing = list((expected - Counter(words(result.stdout))).elements())
            if len(missing) < len(best_missing) or not best_text:
                best_missing, best_text = missing, result.stdout
            if not missing:
                break
    return best_missing, best_text


DOM_CHECK = r'''card => {
    const bounds = card.getBoundingClientRect();
    const failures = [];
    const safeFailures = [];
    const inset = {left: bounds.left + bounds.width * .06,
        right: bounds.right - bounds.width * .06,
        top: bounds.top + bounds.height * .06,
        bottom: bounds.bottom - bounds.height * .06};
    const safe = r => r.left >= inset.left && r.right <= inset.right &&
        r.top >= inset.top && r.bottom <= inset.bottom;
    const rectJSON = r => ({left: r.left - bounds.left, top: r.top - bounds.top,
        width: r.width, height: r.height});
    let textCount = 0;
    const inside = r => r.left >= bounds.left - 0.5 &&
        r.top >= bounds.top - 0.5 && r.right <= bounds.right + 0.5 &&
        r.bottom <= bounds.bottom + 0.5;
    // Include every element with direct text, plus its ancestors up to the card.
    const targets = new Set();
    for (const el of [card, ...card.querySelectorAll('*')]) {
        if ([...el.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim())) {
            for (let p = el; p && card.contains(p); p = p.parentElement) targets.add(p);
        }
    }
    for (const el of targets) {
        const s = getComputedStyle(el), r = el.getBoundingClientRect();
        const reasons = [];
        const textNodes = [...el.childNodes].filter(n =>
            n.nodeType === Node.TEXT_NODE && n.textContent.trim());
        if (textNodes.length) {
            textCount++;
            if (!safe(r)) safeFailures.push({tag: el.tagName,
                reason: 'element outside safe area', rect: rectJSON(r)});
            for (const node of textNodes) {
                const range = document.createRange(); range.selectNodeContents(node);
                for (const rect of range.getClientRects()) {
                    if (!safe(rect)) safeFailures.push({tag: el.tagName,
                        reason: 'text outside safe area', rect: rectJSON(rect)});
                }
            }
        }
        if (el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight)
            reasons.push('scroll overflow');
        if (s.textOverflow === 'ellipsis') reasons.push('ellipsis');
        if ((s.webkitLineClamp && !['none', '0'].includes(s.webkitLineClamp)) ||
            (s.lineClamp && !['none', '0'].includes(s.lineClamp))) reasons.push('line-clamp');
        if (!inside(r)) reasons.push('element outside card');
        for (const node of el.childNodes) {
            if (node.nodeType !== Node.TEXT_NODE || !node.textContent.trim()) continue;
            const range = document.createRange(); range.selectNodeContents(node);
            if ([...range.getClientRects()].some(rect => !inside(rect)))
                reasons.push('text outside card');
        }
        if (reasons.length) failures.push({tag: el.tagName, reasons});
    }
    return {ok: targets.size > 0 && failures.length === 0, failures,
        safe_area_ok: textCount > 0 && safeFailures.length === 0,
        safe_area_details: {inset_x: bounds.width * .06, inset_y: bounds.height * .06,
            text_elements: textCount, failures: safeFailures}};
}'''


def render(args, report):
    expected = Counter(words(' '.join((args.text, args.author, args.source))))
    parts = urlsplit(args.url)
    params = dict(parse_qsl(parts.fragment, keep_blank_values=True))
    params.update(theme='editorial', width='800')
    for key, value in [('quote', args.text), ('author', args.author)]:
        params[key] = base64.b64encode(value.encode('utf-8')).decode('ascii')
    url = urlunsplit(parts._replace(fragment=urlencode(params)))
    path = Path(report['path'])
    path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        launch_options = {'headless': True}
        if not Path(playwright.chromium.executable_path).exists():
            candidates = ['/opt/ungoogled-chromium/chrome',
                          shutil.which('chromium'), shutil.which('chromium-browser'),
                          shutil.which('google-chrome')]
            executable = next((p for p in candidates if p and Path(p).is_file()), None)
            if executable:
                launch_options['executable_path'] = executable
        browser = playwright.chromium.launch(**launch_options)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1100},
                                          device_scale_factor=2, accept_downloads=True)
            # Export triggers analytics. Keep rendering local, without sending content to trackers.
            context.route('**/*', lambda route: route.fulfill(status=204, body='')
                          if urlsplit(route.request.url).path == '/api/track'
                          else route.continue_()
                          if urlsplit(route.request.url).netloc == parts.netloc
                          or urlsplit(route.request.url).scheme in ('data', 'blob')
                          else route.abort())
            page = context.new_page()
            page.set_default_timeout(15000)
            page.goto(url, wait_until='networkidle', timeout=60000)
            card = page.locator('.quote-card')
            card.wait_for()
            # Verify hydration/URL handling; fall back to actual editable fields if needed.
            for selector, value in [('blockquote', args.text), ('cite', args.author)]:
                field = card.locator(selector)
                if field.inner_text() != value:
                    field.fill(value)
                    field.blur()
            card.evaluate('''(card, source) => {
                const author = card.querySelector('cite');
                const el = document.createElement('div');
                el.dataset.renderSource = 'true'; el.textContent = source;
                el.style.cssText = 'font: 16px/1.6 sans-serif; color: #666; margin-top: 12px; width: 100%; white-space: pre-wrap; overflow-wrap: anywhere';
                author.after(el);
            }''', args.source)
            card.evaluate("""card => {
                Object.assign(card.style, {width: '800px', height: '450px',
                    minWidth: '800px', maxWidth: '800px', minHeight: '450px',
                    maxHeight: '450px', boxSizing: 'border-box', flexShrink: '0',
                    padding: '48px 64px'});
            }""")
            page.evaluate('document.fonts.ready')
            for attempt in range(1, MAX_ATTEMPTS + 1):
                report['tentativas'] = attempt
                if attempt > 1:
                    card.evaluate('''(card, attempt) => {
                        card.style.padding = Math.max(27, 48 - (attempt - 1) * 5) + 'px ' +
                            Math.max(48, 64 - (attempt - 1) * 4) + 'px';
                        for (const el of card.querySelectorAll('blockquote, cite, [data-render-source]')) {
                            if (!el.dataset.initialSize) el.dataset.initialSize = getComputedStyle(el).fontSize;
                            el.style.fontSize = parseFloat(el.dataset.initialSize) * Math.pow(.9, attempt - 1) + 'px';
                            el.style.whiteSpace = 'pre-wrap'; el.style.overflowWrap = 'anywhere';
                            el.style.maxWidth = '100%'; el.style.minWidth = '0';
                        }
                    }''', attempt)
                page.wait_for_timeout(600)  # App padding transition is 400 ms.
                page.evaluate('document.activeElement?.blur()')
                dom = card.evaluate(DOM_CHECK)
                report['overflow_ok'] = dom['ok']
                report['overflow_details'] = dom['failures']
                report['safe_area_ok'] = dom['safe_area_ok']
                report['safe_area_details'] = dom['safe_area_details']
                background = card.evaluate("""card => {
                    const canvas = document.createElement('canvas');
                    canvas.width = canvas.height = 1;
                    const ctx = canvas.getContext('2d');
                    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, 1, 1);
                    ctx.fillStyle = getComputedStyle(card).backgroundColor;
                    ctx.fillRect(0, 0, 1, 1);
                    return [...ctx.getImageData(0, 0, 1, 1).data];
                }""")
                try:
                    page.wait_for_function('document.querySelector("[aria-label=\\"Export options\\"]")?.getAttribute("aria-busy") !== "true"')
                    page.get_by_role('button', name='Export options').click()
                    with page.expect_download(timeout=20000) as download_info:
                        page.get_by_role('button', name='Save as PNG', exact=True).click()
                    download = download_info.value
                    download.save_as(path)
                    if download.failure():
                        raise RuntimeError(download.failure())
                    report['export_method'] = 'app-download'
                except (PlaywrightTimeout, RuntimeError) as exc:
                    print(f'Exportação indisponível; screenshot do cartão: {exc}', file=sys.stderr)
                    page.keyboard.press('Escape')
                    card.screenshot(path=str(path), animations='disabled')
                    report['export_method'] = 'card-screenshot'
                report.update(finalize_png(path, background))
                missing, _ = ocr(path, expected)
                report['palavras_faltantes'] = missing
                report['ocr_ok'] = not missing
                if all(report[key] is True for key in CHECKS):
                    return 0
                print(f'Tentativa {attempt}: validações={ {key: report[key] for key in CHECKS} }, faltantes={missing}', file=sys.stderr)
            return 1
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text', required=True)
    parser.add_argument('--author', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--n', default=datetime.now().strftime('%Y%m%d'))
    parser.add_argument('--url', default='http://127.0.0.1:5173')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.n):
        parser.error('--n deve conter apenas letras, números, _ ou -')
    report = dict(path=str(ROOT / 'out' / f'conselho-{args.n}.png'), tentativas=0,
                  overflow_ok=False, ocr_ok=False, aspect_ok=False, size_ok=False,
                  safe_area_ok=False, safe_area_details={}, width=None, height=None, bytes=None,
                  palavras_faltantes=words(' '.join((args.text, args.author, args.source))))
    try:
        status = render(args, report)
    except Exception as exc:
        report['error'] = str(exc).split('Browser logs:')[0].strip()
        status = 1
    print(json.dumps(report, ensure_ascii=False))
    return status


if __name__ == '__main__':
    sys.exit(main())
