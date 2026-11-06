import os, tempfile, unittest, io, json, zipfile, hashlib
from pathlib import Path
TEMP=tempfile.TemporaryDirectory(); os.environ['CF_DATA']=TEMP.name
from app.main import app,TOKEN,db
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader
from scripts.backup import backup,restore

class StudioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=TestClient(app);cls.c.headers['X-CF-Token']=TOKEN
    def make_estimate(self,key='demo-test-estimate',items=None):
        return self.c.post('/api/clients/1/estimates',json={'title':'Demo estimate','currency':'USD','idempotency_key':key,'items':items or [{'description':'Paint','quantity':'12.5','unit_price':'8.40'},{'description':'Prep','quantity':'2','unit_price':'25'}]})
    def test_01_seed(self):
        self.assertEqual(len(self.c.get('/api/clients').json()),3)
        allrows=sum([self.c.get(f'/api/clients/{c}/workspace').json()['records'] for c in [1,2,3]],[])
        self.assertEqual(sum(r['kind']=='inquiry' for r in allrows),30)
        self.assertEqual(sum(r['kind']=='email' for r in allrows),10)
    def test_02_auth(self):
        self.assertEqual(TestClient(app).get('/api/clients').status_code,401)
        self.assertEqual(self.c.get('/api/clients',headers={'Host':'evil.example'}).status_code,400)
        self.assertEqual(self.c.post('/api/clients/1/tasks',headers={'Origin':'https://evil.example'},json={}).status_code,403)
    def test_03_money_approval_exports(self):
        r=self.make_estimate();self.assertEqual(r.status_code,200,r.text);r=r.json();rid=r['id'];base=f'/api/clients/1/records/{rid}'
        self.assertEqual(json.loads(r['payload'])['total'],'155.00')
        self.assertEqual(self.c.get(base+'/export/pdf').status_code,409)
        self.assertEqual(self.c.post(base+'/status',json={'status':'Completed'}).status_code,409)
        self.assertEqual(self.c.post(base.replace('/1/','/2/')+'/status',json={'status':'Approved'}).status_code,404)
        self.assertEqual(self.c.get(base.replace('/1/','/2/')+'/export/pdf').status_code,404)
        self.assertEqual(self.c.post(base+'/status',json={'status':'Approved'}).status_code,200)
        pdf=self.c.get(base+'/export/pdf');self.assertIn('155.00',PdfReader(io.BytesIO(pdf.content)).pages[0].extract_text())
        csv=self.c.get(base+'/export/csv');self.assertIn(b'155.00',csv.content)
        self.assertIn('supplied data',self.c.get(base+'/export/txt').text)
        self.assertEqual(self.c.post(base+'/status',json={'status':'Completed'}).status_code,200)
        self.assertEqual(self.c.post(base+'/status',json={'status':'Needs Review'}).status_code,409)
    def test_04_idempotency(self):
        a=self.make_estimate('dedup-test-1').json();b=self.make_estimate('dedup-test-1').json();self.assertEqual(a['id'],b['id'])
        self.assertEqual(self.make_estimate('dedup-test-1',[{'description':'Different','quantity':'1','unit_price':'2'}]).status_code,409)
    def test_05_missing_invalid(self):
        r=self.make_estimate('missing-test',[{'description':'Unknown','quantity':None,'unit_price':'5'}]).json()
        self.assertTrue(json.loads(r['payload'])['missing'])
        self.assertEqual(self.c.post(f"/api/clients/1/records/{r['id']}/status",json={'status':'Approved'}).status_code,409)
        for price in ['-1','NaN','Infinity','9999999999999']:
            self.assertEqual(self.make_estimate('invalid-test-'+price,[{'description':'Bad','quantity':'1','unit_price':price}]).status_code,422)
        self.assertEqual(self.c.post('/api/clients/1/emails',json={'title':'x','source':'x','follow_up':'bad','idempotency_key':'bad-date-test'}).status_code,422)
    def test_06_files_and_archive(self):
        originals={}
        for i in range(20):
            b=io.BytesIO();Image.new('RGB',(32+i,24),(i*10,80,120)).save(b,format='PNG');raw=b.getvalue()
            cid=i%3+1;r=self.c.post(f'/api/clients/{cid}/files/demo-project',files={'file':('../../unsafe.png',raw,'image/png')});self.assertEqual(r.status_code,200,r.text)
            originals[r.json()['name']]=raw
            if i==0:
                dup=self.c.post('/api/clients/1/files/demo-project',files={'file':('same.png',raw)});self.assertTrue(dup.json()['duplicate'])
        r=self.c.post('/api/clients/1/files/demo-project/delivery').json();rid=r['id'];base=f'/api/clients/1/records/{rid}'
        self.assertEqual(self.c.get(base+'/archive').status_code,409)
        self.c.post(base+'/status',json={'status':'Approved'})
        z=zipfile.ZipFile(io.BytesIO(self.c.get(base+'/archive').content))
        self.assertIn('index.csv',z.namelist());self.assertEqual(len([n for n in z.namelist() if n.endswith('.png')]),7)
        for name in z.namelist():
            if name.endswith('.png'): self.assertEqual(z.read(name),originals[name])
        self.assertEqual(self.c.get(base.replace('/1/','/2/')+'/archive').status_code,404)
        bad=self.c.post('/api/clients/1/files/demo-project',files={'file':('fake.png',b'bad')});self.assertEqual(bad.status_code,400)
        self.assertEqual(self.c.post('/api/clients/1/files/bad.project',files={'file':('a.png',raw)}).status_code,400)
        self.assertEqual(self.c.post('/api/clients/1/files/demo-project',files={'file':('large.png',b'x'*(10*1024*1024+1))}).status_code,413)
        with db() as c:self.assertEqual(c.execute('SELECT count(*) FROM files').fetchone()[0],20)
    def test_07_backup_restore(self):
        with tempfile.TemporaryDirectory() as t:
            b=Path(t)/'backup';r=Path(t)/'restore';manifest=backup(TEMP.name,b);restore(b,r)
            for name,digest in manifest.items(): self.assertEqual(hashlib.sha256((r/name).read_bytes()).hexdigest(),digest)
            with self.assertRaises(ValueError):restore(b,r)
            (b/'studio.db').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):restore(b,Path(t)/'corrupt-restore')
    def test_08_rounding_csv_injection(self):
        r=self.make_estimate('rounding-test',[{'description':'=HYPERLINK("bad")','quantity':'1','unit_price':'0.005'}]).json();p=json.loads(r['payload']);self.assertEqual(p['total'],'0.01')
        base=f"/api/clients/1/records/{r['id']}";self.c.post(base+'/status',json={'status':'Approved'})
        self.assertIn("'=HYPERLINK",self.c.get(base+'/export/csv').text)
    def test_09_email_tasks_reports(self):
        r=self.c.post('/api/clients/2/emails',json={'title':'Demo reply','source':'Please quote my project','follow_up':'2026-11-10','idempotency_key':'email-demo-test'}).json()
        self.assertEqual(json.loads(r['payload'])['category'],'estimate_request');self.assertIn('Not sent',json.loads(r['payload'])['draft'])
        self.assertEqual(self.c.post('/api/clients/2/tasks',json={'title':'Call scope review','notes':'Demo only','follow_up':'2026-11-10','idempotency_key':'task-demo-test'}).status_code,200)
        self.assertTrue(self.c.get('/api/clients/2/report').json()['demo'])
        self.assertTrue(self.c.get('/api/clients/1/workspace').json()['audit'])
    def test_10_revenue(self):
        payload={'month':'2026-11','currency':'USD','cents':4900,'idempotency_key':'revenue-demo-test'}
        self.assertEqual(self.c.post('/api/clients/1/revenue',json=payload).status_code,200)
        self.assertTrue(self.c.post('/api/clients/1/revenue',json=payload).json()['duplicate'])
        payload['cents']=59900
        self.assertEqual(self.c.post('/api/clients/1/revenue',json=payload).status_code,409)
        payload['month']='2026-99'
        self.assertEqual(self.c.post('/api/clients/1/revenue',json=payload).status_code,422)
    def test_11_pages(self):
        for p in ['/','/studio','/static/studio.js','/static/style.css']:self.assertEqual(self.c.get(p).status_code,200)
        self.assertEqual(self.c.get('/api/clients/999/workspace').status_code,404)

if __name__=='__main__':unittest.main(verbosity=2)
