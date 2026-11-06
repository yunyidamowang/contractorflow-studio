"""Optional real Chrome QA. Requires existing agent-browser and a running local demo. Creates fictional records only."""
import subprocess,json,time
from pathlib import Path
base=Path(__file__).resolve().parents[1]; out=base/'artifacts/browser-qa';out.mkdir(parents=True,exist_ok=True)
log=[]
def ab(*args):
 r=subprocess.run(['agent-browser','--session','cf-qa',*args],capture_output=True,text=True,timeout=35)
 if r.returncode:raise RuntimeError(r.stderr+r.stdout)
 if args[0] in ("click","select"):time.sleep(1)
 return r.stdout
ab('set','viewport','390','844');ab('open','http://127.0.0.1:8765/studio');ab('fill','#token',(base/'data/.token').read_text().strip());ab('click','#unlock');time.sleep(1)
log.append(ab('eval',"JSON.stringify({client:document.querySelector('#client-name').textContent,rows:document.querySelectorAll('#records tr').length})"))
ab('fill','#estimate-form input[name=title]','Browser QA estimate');ab('click','#estimate-submit');time.sleep(1)
state=ab('eval',"document.querySelector('#records tr').innerText");assert 'estimate / Browser QA estimate' in state,state;log.append(state)
ab('click','#records tr:first-child button');time.sleep(.7)
for fmt in ['csv','pdf','txt']:
 ab('download',f'#records tr:first-child button:nth-of-type({3+["csv","pdf","txt"].index(fmt)})',str((out/f'estimate.{fmt}').resolve()))
ab('click','#records tr:first-child button:first-of-type');time.sleep(.3)
ab('click','#email-form button');time.sleep(.3);ab('click','#records tr:first-child button');time.sleep(.7)
ab('download','#records tr:first-child button:nth-of-type(3)',str((out/'email.txt').resolve()))
ab('click','#records tr:first-child button:first-of-type')
file=next((base/'data/files/1/demo-project').glob('*.png'))
ab('fill','#files-form input[name=project]','browser-qa-'+str(int(time.time())));ab('upload','#files-form input[type=file]',str(file.resolve()));ab('click','#files-form button[type=submit]') if False else ab('click','#files-form button:first-of-type');time.sleep(.4)
ab('click','#delivery');time.sleep(.4);ab('click','#records tr:first-child button');time.sleep(.7)
ab('download','#records tr:first-child button:nth-of-type(3)',str((out/'files.zip').resolve()));ab('click','#records tr:first-child button:first-of-type')
ab('fill','#task-form input[name=title]','Browser QA task');ab('click','#task-form button');time.sleep(.3)
ab('click','#report');time.sleep(.5);log.append(ab('eval',"document.querySelector('#daily').textContent"))
ab('fill','.estimate-line:first-child input[name=unit_price]','-1');ab('click','#estimate-submit');log.append(ab('eval',"document.querySelector('#estimate-lines input[name=unit_price]').validity.valid"))
ab('select','#client','2');time.sleep(.4);log.append(ab('eval',"JSON.stringify({client:document.querySelector('#client-name').textContent,hasOtherClientEstimate:document.querySelector('#records').textContent.includes('Browser QA estimate')})"))
ab('eval','scrollTo(0,0)');ab('set','viewport','1440','1000');ab('screenshot',str((out/'desktop-studio.png').resolve()));ab('set','viewport','390','844');ab('screenshot',str((out/'mobile-studio.png').resolve()))
log.append(ab('eval',"JSON.stringify({width:innerWidth,scroll:document.documentElement.scrollWidth})"))
ab('open','http://127.0.0.1:8765/');ab('fill','#brief textarea','Fictional painting project; organize supplied estimate inputs.');ab('click','#brief button');log.append(ab('eval',"document.querySelector('#brief-output').textContent"));ab('eval','scrollTo(0,0)');ab('screenshot',str((out/'mobile-website.png').resolve()));ab('set','viewport','1440','1000');ab('screenshot',str((out/'desktop-website.png').resolve()));log.append(ab('errors'))
(out/'results.txt').write_text('\n'.join(log));print('\n'.join(log));print('Browser downloads and screenshots saved')
