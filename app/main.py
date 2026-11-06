from pathlib import Path
import csv, hashlib, io, json, os, secrets, sqlite3, time, zipfile
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from typing import Literal
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from PIL import Image
from pypdf import PdfReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('CF_DATA', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
Image.MAX_IMAGE_PIXELS = 20_000_000
TOKEN_FILE = DATA / '.token'
if not TOKEN_FILE.exists():
    TOKEN_FILE.write_text(secrets.token_urlsafe(32))
    TOKEN_FILE.chmod(0o600)
TOKEN = TOKEN_FILE.read_text().strip()
app = FastAPI(title='ContractorFlow Studio — Demo', docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=ROOT / 'app/static'), name='static')

@contextmanager
def db():
    conn = sqlite3.connect(DATA / 'studio.db')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def now(): return datetime.now(timezone.utc).isoformat()
def audit(c, event, client, detail=''):
    c.execute('INSERT INTO audit(event,client_id,detail,created) VALUES(?,?,?,?)',(event,client,detail,now()))

def init():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY,name TEXT,service TEXT,timezone TEXT,package TEXT);
        CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY,client_id INTEGER NOT NULL REFERENCES clients(id),kind TEXT,title TEXT,payload TEXT,status TEXT DEFAULT 'Pending',created TEXT,updated TEXT,idem TEXT,UNIQUE(client_id,idem));
        CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,client_id INTEGER REFERENCES clients(id),project TEXT,name TEXT,sha TEXT,kind TEXT,size INTEGER,UNIQUE(client_id,project,sha));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,event TEXT,client_id INTEGER,detail TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS revenue(id INTEGER PRIMARY KEY,client_id INTEGER REFERENCES clients(id),month TEXT,currency TEXT,cents INTEGER,idem TEXT,UNIQUE(client_id,idem));
        ''')
        if 'idem' not in {r['name'] for r in c.execute('PRAGMA table_info(revenue)')}:
            c.execute('ALTER TABLE revenue ADD COLUMN idem TEXT')
            c.execute('CREATE UNIQUE INDEX IF NOT EXISTS revenue_idem ON revenue(client_id,idem)')
        if not c.execute('SELECT 1 FROM clients').fetchone():
            c.executemany('INSERT INTO clients VALUES(?,?,?,?,?)',[(1,'Demo · Cedar Paint','Painting','America/New_York','Trial $49'),(2,'Demo · Harbour Garden','Gardening','Australia/Sydney','Basic $299'),(3,'Demo · Clear Home','Cleaning','America/Los_Angeles','Advanced $599')])
            for i in range(30):
                cid=i%3+1
                c.execute('INSERT INTO records(client_id,kind,title,payload,created,updated,idem) VALUES(?,?,?,?,?,?,?)',(cid,'inquiry',f'Demo inquiry {i+1}',json.dumps({'message':'Please organize the supplied project information.','follow_up':'2026-11-09','suggestion':'Confirm project scope and availability.'}),now(),now(),f'seed-inquiry-{i}'))
            for i in range(10):
                c.execute('INSERT INTO records(client_id,kind,title,payload,status,created,updated,idem) VALUES(?,?,?,?,?,?,?,?)',(i%3+1,'email',f'Demo email {i+1}',json.dumps({'source':'Could you send the estimate?','category':'estimate_request','draft':'Hello, thank you for your inquiry. Could you confirm the project scope and preferred timing? We will prepare a draft for your review.','suggestion':'Needs information','follow_up':'2026-11-09'}),'Needs Review',now(),now(),f'seed-email-{i}'))
            audit(c,'demo_seed',None,'3 clients, 30 inquiries, 10 emails; fictional')
init()

@app.middleware('http')
async def protect(request: Request, call_next):
    if request.headers.get('host','').split(':')[0] not in ('127.0.0.1','localhost','testserver'):
        return Response('Invalid host',status_code=400)
    if request.url.path.startswith('/api/') and request.headers.get('x-cf-token') != TOKEN:
        return Response('Unauthorized',status_code=401)
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765'):
            return Response('Invalid origin',status_code=403)
    if request.method in ('POST','PUT','PATCH'):
        chunks=[]; size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>11*1024*1024:
                return Response('Request exceeds 11 MiB',status_code=413)
            chunks.append(chunk)
        request._body=b''.join(chunks)
    start=time.monotonic()
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
    response.headers['Cache-Control']='no-store'
    response.headers['X-Process-Time']=str(round(time.monotonic()-start,4))
    return response

@app.get('/')
def home(): return FileResponse(ROOT/'app/static/index.html')
@app.get('/studio')
def studio(): return FileResponse(ROOT/'app/static/studio.html')

def client(c,cid):
    row=c.execute('SELECT * FROM clients WHERE id=?',(cid,)).fetchone()
    if not row: raise HTTPException(404,'Client not found')
    return dict(row)
def record(c,cid,rid):
    r=c.execute('SELECT * FROM records WHERE client_id=? AND id=?',(cid,rid)).fetchone()
    if not r: raise HTTPException(404,'Record not found in this client')
    return dict(r)

class Item(BaseModel):
    description: str = Field(min_length=1,max_length=200)
    quantity: Decimal | None = Field(default=None,ge=0,le=1000000,max_digits=12,decimal_places=4)
    unit_price: Decimal | None = Field(default=None,ge=0,le=1000000,max_digits=12,decimal_places=4)
    notes: str = Field(default='',max_length=500)
class Estimate(BaseModel):
    title: str = Field(min_length=1,max_length=100)
    currency: Literal['USD','AUD']='USD'
    items: list[Item] = Field(min_length=1,max_length=100)
    idempotency_key: str = Field(min_length=8,max_length=100)
class Message(BaseModel):
    title: str = Field(min_length=1,max_length=100)
    source: str = Field(min_length=1,max_length=5000)
    follow_up: str
    idempotency_key: str = Field(min_length=8,max_length=100)
    @field_validator('follow_up')
    @classmethod
    def date_valid(cls,v):
        from datetime import date
        date.fromisoformat(v)
        return v
class Transition(BaseModel):
    status: Literal['Pending','Processing','Needs Review','Approved','Completed','Failed']
class ClientInput(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    service: str = Field(min_length=1,max_length=100)
    timezone: str
    package: str = Field(min_length=1,max_length=100)
    @field_validator('timezone')
    @classmethod
    def zone_valid(cls,v):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try: ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError): raise ValueError('Unknown timezone')
        return v
class TaskInput(BaseModel):
    title: str = Field(min_length=1,max_length=100)
    notes: str = Field(default='',max_length=2000)
    follow_up: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    idempotency_key: str = Field(min_length=8,max_length=100)
    @field_validator('follow_up')
    @classmethod
    def valid_date(cls,v):
        from datetime import date
        date.fromisoformat(v)
        return v

class Revenue(BaseModel):
    idempotency_key: str = Field(min_length=8,max_length=100)
    month: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    currency: Literal['USD','AUD']
    cents: int = Field(ge=0,le=100000000)

def save(c,cid,kind,title,payload,key):
    c.execute('BEGIN IMMEDIATE')
    old=c.execute('SELECT * FROM records WHERE client_id=? AND idem=?',(cid,key)).fetchone()
    encoded=json.dumps(payload,sort_keys=True)
    if old:
        if old['kind']!=kind or old['title']!=title or old['payload']!=encoded: raise HTTPException(409,'Idempotency key reused with different content')
        return dict(old)
    rid=c.execute("INSERT INTO records(client_id,kind,title,payload,status,created,updated,idem) VALUES(?,?,?,?, 'Needs Review',?,?,?)",(cid,kind,title,encoded,now(),now(),key)).lastrowid
    audit(c,'create_'+kind,cid,str(rid))
    return record(c,cid,rid)

@app.get('/api/clients')
def clients():
    with db() as c: return [dict(r) for r in c.execute('SELECT * FROM clients')]
@app.post('/api/clients')
def add_client(v:ClientInput):
    with db() as c:
        cid=c.execute('INSERT INTO clients(name,service,timezone,package) VALUES(?,?,?,?)',('Demo · '+v.name,v.service,v.timezone,v.package)).lastrowid
        audit(c,'create_client',cid)
        return client(c,cid)
@app.get('/api/clients/{cid}/workspace')
def workspace(cid:int):
    with db() as c:
        info=client(c,cid)
        rows=[dict(r) for r in c.execute('SELECT * FROM records WHERE client_id=? ORDER BY id DESC',(cid,))]
        files=[dict(r) for r in c.execute('SELECT * FROM files WHERE client_id=?',(cid,))]
        logs=[dict(r) for r in c.execute('SELECT * FROM audit WHERE client_id=? ORDER BY id DESC LIMIT 50',(cid,))]
        rev=[dict(r) for r in c.execute('SELECT * FROM revenue WHERE client_id=?',(cid,))]
        return dict(client=info,records=rows,files=files,audit=logs,revenue=rev,demo=True)
@app.post('/api/clients/{cid}/estimates')
def estimate(cid:int,v:Estimate):
    missing=[]; lines=[]; total=Decimal('0')
    for i,x in enumerate(v.items,1):
        amount=None
        if x.quantity is None or x.unit_price is None: missing.append(f'Line {i}: quantity or unit price missing')
        else:
            amount=(x.quantity*x.unit_price).quantize(Decimal('.01'),rounding=ROUND_HALF_UP); total+=amount
        lines.append(dict(description=x.description,quantity=str(x.quantity) if x.quantity is not None else None,unit_price=str(x.unit_price) if x.unit_price is not None else None,amount=str(amount) if amount is not None else None,notes=x.notes))
    payload=dict(currency=v.currency,items=lines,total=str(total),missing=missing,summary=f'Draft based only on supplied data. {len(lines)} line items. Known subtotal {v.currency} {total}. Tax, scope and missing values require customer confirmation. No tax or materials assumed.')
    with db() as c:
        client(c,cid)
        return save(c,cid,'estimate',v.title,payload,v.idempotency_key)
@app.post('/api/clients/{cid}/emails')
def email(cid:int,v:Message):
    category='estimate_request' if any(t in v.source.lower() for t in ['quote','estimate','price']) else 'general_inquiry'
    payload=dict(source=v.source,category=category,follow_up=v.follow_up,suggestion='Confirm scope; retain current client status until review.',draft='Hello,\n\nThank you for getting in touch. Could you please confirm the project scope, location and preferred timing? We will review the information you provide and follow up with the next steps.\n\nKind regards,\nContractorFlow Back Office\n\nDEMO - DRAFT ONLY. Not sent.')
    with db() as c:
        client(c,cid)
        return save(c,cid,'email',v.title,payload,v.idempotency_key)
@app.post('/api/clients/{cid}/tasks')
def task(cid:int,v:TaskInput):
    with db() as c:
        client(c,cid)
        return save(c,cid,'task',v.title,dict(notes=v.notes,follow_up=v.follow_up),v.idempotency_key)
@app.post('/api/clients/{cid}/revenue')
def revenue(cid:int,v:Revenue):
    with db() as c:
        client(c,cid)
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT * FROM revenue WHERE client_id=? AND idem=?',(cid,v.idempotency_key)).fetchone()
        if old:
            if (old['month'],old['currency'],old['cents'])!=(v.month,v.currency,v.cents): raise HTTPException(409,'Idempotency key reused')
            return {'demo':True,'duplicate':True}
        c.execute('INSERT INTO revenue(client_id,month,currency,cents,idem) VALUES(?,?,?,?,?)',(cid,v.month,v.currency,v.cents,v.idempotency_key))
        audit(c,'demo_revenue',cid)
    return {'demo':True}

ALLOWED={'Pending':{'Processing','Failed'},'Processing':{'Needs Review','Failed'},'Needs Review':{'Approved','Failed'},'Approved':{'Completed','Needs Review'},'Failed':{'Pending'},'Completed':set()}
@app.post('/api/clients/{cid}/records/{rid}/status')
def status(cid:int,rid:int,v:Transition):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        r=record(c,cid,rid)
        if v.status==r['status']: return r
        if v.status not in ALLOWED[r['status']]: raise HTTPException(409,'Invalid approval transition')
        if v.status=='Approved' and r['kind']=='estimate' and json.loads(r['payload'])['missing']: raise HTTPException(409,'Missing fields must be resolved in a new draft')
        c.execute('UPDATE records SET status=?,updated=? WHERE id=? AND client_id=?',(v.status,now(),rid,cid))
        audit(c,'status_'+v.status,cid,str(rid))
        return record(c,cid,rid)

def safe_csv(rows):
    def safe(v):
        s=str(v if v is not None else '')
        return "'"+s if s.lstrip().startswith(('=','+','-','@')) else s
    out=io.StringIO(); csv.writer(out).writerows([[safe(v) for v in row] for row in rows]); return out.getvalue().encode('utf-8-sig')

def pdf_bytes(r,p,name):
    out=io.BytesIO(); styles=getSampleStyleSheet()
    story=[Paragraph('DEMO / ESTIMATE DRAFT',styles['Title']),Paragraph(escape(name),styles['Heading2']),Paragraph(escape(r['title']),styles['Normal']),Spacer(1,16)]
    rows=[['Description','Qty','Unit price','Amount']]
    for x in p['items']: rows.append([Paragraph(escape(x['description']),styles['Normal']),x['quantity'] or 'TBC',x['unit_price'] or 'TBC',x['amount'] or 'TBC'])
    story.extend([Table(rows,colWidths=[270,60,80,80],repeatRows=1),Spacer(1,20),Paragraph(f"Known subtotal: {p['currency']} {p['total']}",styles['Heading2']),Paragraph(escape(p['summary']),styles['Normal'])])
    for x in p['items']:
        if x['notes']: story.append(Paragraph(escape(x['description']+': '+x['notes']),styles['Normal']))
    for m in p['missing']: story.append(Paragraph(escape(m),styles['Normal']))
    SimpleDocTemplate(out).build(story); return out.getvalue()
@app.get('/api/clients/{cid}/records/{rid}/export/{fmt}')
def export(cid:int,rid:int,fmt:Literal['csv','pdf','txt']):
    with db() as c:
        r=record(c,cid,rid); cl=client(c,cid); p=json.loads(r['payload'])
        if r['status'] not in ('Approved','Completed'): raise HTTPException(409,'Approval required before export')
        if r['kind']=='estimate':
            if fmt=='pdf': content=pdf_bytes(r,p,cl['name']); media='application/pdf'
            elif fmt=='csv': content=safe_csv([['DEMO',cl['name'],p['currency']],['description','quantity','unit_price','amount','notes']]+[[x[k] for k in ('description','quantity','unit_price','amount','notes')] for x in p['items']]+[['Known subtotal','','',p['total']]]); media='text/csv'
            else: content=p['summary'].encode(); media='text/plain'
        elif fmt=='txt': content=p.get('draft',json.dumps(p,indent=2)).encode(); media='text/plain'
        else: raise HTTPException(400,'Use txt for this record')
        audit(c,'export_'+fmt,cid,str(rid))
        return Response(content,media_type=media,headers={'Content-Disposition':f'attachment; filename="demo-{rid}.{fmt}"'})

@app.post('/api/clients/{cid}/files/{project}')
async def upload(cid:int,project:str,file:UploadFile=File(...)):
    if not project.isascii() or not project.replace('-','').replace('_','').isalnum() or len(project)>60: raise HTTPException(400,'Use a short alphanumeric project ID')
    content=await file.read(10*1024*1024+1)
    if not content or len(content)>10*1024*1024: raise HTTPException(413,'File must be 1 byte to 10 MiB')
    sha=hashlib.sha256(content).hexdigest()
    try:
        if content.startswith(b'%PDF-'):
            reader=PdfReader(io.BytesIO(content))
            if reader.is_encrypted or len(reader.pages)>200: raise ValueError()
            kind='pdf'
        else:
            with Image.open(io.BytesIO(content)) as img:
                if img.width*img.height>Image.MAX_IMAGE_PIXELS: raise ValueError()
                if img.format not in ('JPEG','PNG'): raise ValueError()
                kind='jpg' if img.format=='JPEG' else 'png'
                img.verify()
    except Exception: raise HTTPException(400,'Only valid non-encrypted PDF, PNG or JPEG accepted')
    with db() as c:
        client(c,cid)
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT * FROM files WHERE client_id=? AND project=? AND sha=?',(cid,project,sha)).fetchone()
        if old: return dict(duplicate=True,file=dict(old))
        folder=DATA/'files'/str(cid)/project; folder.mkdir(parents=True,exist_ok=True)
        name=f'{project}-{sha}.{kind}'
        (folder/name).write_bytes(content)
        fid=c.execute('INSERT INTO files(client_id,project,name,sha,kind,size) VALUES(?,?,?,?,?,?)',(cid,project,name,sha,kind,len(content))).lastrowid
        audit(c,'import_file',cid,str(fid))
        return dict(duplicate=False,id=fid,name=name)
@app.post('/api/clients/{cid}/files/{project}/delivery')
def file_delivery(cid:int,project:str):
    with db() as c:
        client(c,cid)
        files=[dict(r) for r in c.execute('SELECT * FROM files WHERE client_id=? AND project=? ORDER BY id',(cid,project))]
        if not files: raise HTTPException(404,'No files')
        digest=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
        return save(c,cid,'files','Demo project files',dict(project=project,files=files),'files-'+digest)
@app.get('/api/clients/{cid}/records/{rid}/archive')
def archive(cid:int,rid:int):
    with db() as c:
        r=record(c,cid,rid)
        if r['kind']!='files' or r['status'] not in ('Approved','Completed'): raise HTTPException(409,'Approved file delivery required')
        p=json.loads(r['payload']); out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            rows=[['Demo','name','sha256','bytes','type']]
            for f in p['files']:
                path=DATA/'files'/str(cid)/p['project']/f['name']
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=f['sha']: raise HTTPException(409,'Source file missing or changed; restore and review before delivery')
                z.write(path,f['name']); rows.append(['Demo',f['name'],f['sha'],f['size'],f['kind']])
            z.writestr('index.csv',safe_csv(rows))
            z.writestr('README.txt','DEMO. Grouped by operator supplied project only. Exact-byte deduplication. No engineering or safety assessment. Originals unchanged; metadata retained. Do not share without authorization.')
        audit(c,'export_archive',cid,str(rid))
        return Response(out.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="demo-project-{rid}.zip"'})
@app.get('/api/clients/{cid}/report')
def report(cid:int):
    with db() as c:
        client(c,cid)
        counts={r['status']:r['n'] for r in c.execute('SELECT status,count(*) n FROM records WHERE client_id=? GROUP BY status',(cid,))}
        return {'demo':True,'generated':now(),'counts':counts,'note':'Internal daily summary. Follow-up dates are stored in ISO format; no messages sent.'}
