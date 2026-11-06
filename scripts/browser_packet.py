"""Real Chrome quote-packet acceptance; local sample service must be running."""
import io
import json
import sqlite3
import subprocess
import time
import zipfile
from pathlib import Path
from pypdf import PdfReader

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / 'artifacts/round2'

def ab(*args):
    result = subprocess.run(['agent-browser', '--session', 'cf-packet', *args], capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout

def click(selector):
    ab('eval', 'document.querySelector(' + json.dumps(selector) + ').click()')
    time.sleep(1)

ab('--executable-path', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', 'open', 'http://127.0.0.1:8765/studio')
ab('set', 'viewport', '1440', '1000')
ab('fill', '#token', (BASE / 'data/.token').read_text().strip())
click('#unlock')
with sqlite3.connect(BASE / 'data/studio.db') as db:
    fid = db.execute('SELECT id FROM files WHERE client_id=1 LIMIT 1').fetchone()[0]
ab('fill', '#estimate-form input[name=attachment_ids]', str(fid))
ab('fill', '#estimate-form textarea[name=source_notes]', 'SAMPLE contractor notes for browser quote packet acceptance.')
click('#estimate-submit')
assert 'Needs Review' in ab('eval', 'document.querySelector("#records tr").innerText')
click('#records tr:first-child td:last-child > button:first-of-type')
ab('eval', 'document.querySelector("#records tr:first-child td:last-child > button:nth-of-type(3)").id="packet-download"')
ab('download', '#packet-download', str(OUT / 'quote-packet.zip'))
with zipfile.ZipFile(OUT / 'quote-packet.zip') as archive:
    names = archive.namelist()
    assert any(name.startswith('sample-attachments/') for name in names), names
    csv = archive.read('sample-line-items.csv').decode('utf-8-sig')
    assert 'SAMPLE DATA' in csv and '155.00' in csv
    assert 'browser quote packet acceptance' in archive.read('sample-packet.txt').decode()
    pdf = next(name for name in names if name.endswith('.pdf'))
    text = ''.join(page.extract_text() for page in PdfReader(io.BytesIO(archive.read(pdf))).pages)
    assert 'SAMPLE DATA' in text and '155.00' in text
ab('screenshot', str(OUT / 'quote-packet-browser.png'))
assert not ab('errors').strip()
print('PASS: actual Chrome quote approval, packet ZIP download, sample PDF/CSV, 155.00 subtotal, source notes and referenced attachment.')
