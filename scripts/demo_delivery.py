"""Create reproducible fictional files and three local deliveries; never sends data."""
import io, json
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image,ImageDraw
from app.main import app,TOKEN,ROOT

def main():
    out=ROOT/'artifacts'/'demo-delivery';out.mkdir(parents=True,exist_ok=True)
    client=TestClient(app);client.headers['X-CF-Token']=TOKEN
    def post(path,data):
        r=client.post('/api/'+path,json=data);r.raise_for_status();return r.json()
    def approve(r,cid):
        if r['status']=='Needs Review': post(f"clients/{cid}/records/{r['id']}/status",{'status':'Approved'})
    r=post('clients/1/estimates',{'title':'Demo · Interior painting estimate inputs','currency':'USD','items':[{'description':'Wall painting, supplied scope','quantity':'12.5','unit_price':'8.40','notes':'Fictional customer supplied price and quantity'},{'description':'Preparation','quantity':'2','unit_price':'25','notes':'Tax and final scope require confirmation'}],'idempotency_key':'demo-delivery-estimate-v1'})
    approve(r,1)
    for fmt in ['csv','pdf','txt']:
        response=client.get(f"/api/clients/1/records/{r['id']}/export/{fmt}");response.raise_for_status();(out/f'estimate-draft.{fmt}').write_bytes(response.content)
    post(f"clients/1/records/{r['id']}/status",{'status':'Completed'})
    r=post('clients/2/emails',{'title':'Demo · Lead follow-up','source':'Could you provide a quote? Our project details are not finalized.','follow_up':'2026-11-09','idempotency_key':'demo-delivery-email-v1'})
    approve(r,2)
    response=client.get(f"/api/clients/2/records/{r['id']}/export/txt");response.raise_for_status();(out/'follow-up-draft.txt').write_bytes(response.content)
    post(f"clients/2/records/{r['id']}/status",{'status':'Completed'})
    for i in range(20):
        img=Image.new('RGB',(640,420),('#e7ede6' if i%2 else '#d6e3dc'));draw=ImageDraw.Draw(img);draw.rectangle((80,100,560,330),outline='#226658',width=4);draw.text((100,150),f'DEMO / SYNTHETIC FILE {i+1}\nNo construction assessment',fill='#182d31');b=io.BytesIO();img.save(b,format='PNG')
        cid=i%3+1;response=client.post(f'/api/clients/{cid}/files/demo-project',files={'file':(f'demo-{i+1}.png',b.getvalue(),'image/png')});response.raise_for_status()
    r=post('clients/1/files/demo-project/delivery',{})
    approve(r,1)
    response=client.get(f"/api/clients/1/records/{r['id']}/archive");response.raise_for_status();(out/'project-photo-organization.zip').write_bytes(response.content)
    post(f"clients/1/records/{r['id']}/status",{'status':'Completed'})
    (out/'README.md').write_text('# Demo delivery\nAll data and images are fictional. Approval transitions performed by the simulation script, not by a real customer.\n\nKnown subtotal USD 155.00, tax not calculated. CSV + PDF + English summary; follow-up draft never sent; ZIP contains 7 of the 20 synthetic files belonging to Demo client 1 and an index. Other files remain isolated in clients 2 and 3.\n')
    print('Three fictional deliveries created; 20 synthetic files across 3 clients. Artifacts: artifacts/demo-delivery')
if __name__=='__main__':main()
