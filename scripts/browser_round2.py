"""Round-two real Chrome acceptance, requires running local sample app."""
import subprocess,json,time,io
from pathlib import Path
from pypdf import PdfReader
BASE=Path(__file__).resolve().parents[1];OUT=BASE/'artifacts/round2';OUT.mkdir(parents=True,exist_ok=True)
results=[]
def ab(*args):
    if args[0]=='click': args=('eval','document.querySelector('+json.dumps(args[1])+').click()')
    if args[0]=='download':
        ab('eval','document.querySelectorAll("#qa-download").forEach(x=>x.removeAttribute("id"));document.querySelector('+json.dumps(args[1])+').id="qa-download"')
        args=('download','#qa-download',args[2])
    r=subprocess.run(['agent-browser','--session','cf-round2',*args],capture_output=True,text=True,timeout=35)
    if r.returncode:raise RuntimeError(r.stdout+r.stderr)
    if args[0] in ['click','select','open','eval']:time.sleep(1)
    return r.stdout
for width in [1440,390]:
    ab('set','viewport',str(width),'900');ab('open','http://127.0.0.1:8765/studio')
    ab('fill','#token',(BASE/'data/.token').read_text().strip());ab('click','#unlock')
    assert 'SAMPLE MODE' in ab('eval','document.body.textContent')
    ab('check','#missing-next');time.sleep(.7)
    assert ab('eval','document.querySelectorAll("#followup-board > div").length').strip()=='1'
    ab('download','#board-export',str((OUT/f'board-{width}.csv').resolve()))
    assert 'SAMPLE DATA' in (OUT/f'board-{width}.csv').read_text(encoding='utf-8-sig')
    ab('select','#followup-board select','questions');ab('click','#followup-board button')
    for tone in ['friendly','missing_info','final_check']:
        ab('select','#email-form select[name=tone]',tone);ab('click','#email-form button')
        row=ab('eval','document.querySelector("#records tr").innerText');assert 'Needs Review' in row
        ab('click','#records tr:first-child summary')
        ab('fill','#records tr:first-child textarea',f'Hello, sample edited {tone} reply. Not sent.')
        ab('click','#records tr:first-child details button')
        assert 'Needs Review' in ab('eval','document.querySelector("#records tr").innerText')
        ab('click','#records tr:first-child td:last-child > button:first-of-type')
        ab('download','#records tr:first-child td:last-child > button:nth-of-type(3)',str((OUT/f'{tone}-{width}.txt').resolve()))
        assert 'sample edited '+tone in (OUT/f'{tone}-{width}.txt').read_text()
        assert 'SAMPLE DATA' in (OUT/f'{tone}-{width}.txt').read_text()
    ab('click','#photo-form button')
    ab('click','#records tr:first-child summary')
    preview=json.loads(ab('eval','document.querySelector("#records tr pre").textContent'));assert 'Invoice-ready: false' in preview and 'completion' in preview
    ab('click','#records tr:first-child td:last-child > button:first-of-type')
    ab('download','#records tr:first-child td:last-child > button:nth-of-type(4)',str((OUT/f'exceptions-{width}.pdf').resolve()))
    text=''.join(p.extract_text() for p in PdfReader(OUT/f'exceptions-{width}.pdf').pages)
    assert 'SAMPLE DATA' in text and 'completion' in text
    ab('eval','scrollTo(0,0)');ab('screenshot',str((OUT/f'studio-{width}.png').resolve()))
    assert ab('eval','document.documentElement.scrollWidth<=innerWidth').strip()=='true'
    results.append(f'{width}px: board filter/status/CSV, three tones/edit/reapproval/download, missing-photo report/PDF; sample marks and no overflow passed')
results.append(ab('errors'));(OUT/'results.txt').write_text('\n'.join(results));print('\n'.join(results))
