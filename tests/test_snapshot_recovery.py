import base64
import hashlib
import io
import json
import socket
import ssl
import http.client
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock
from automation.dispatcher import GitHub, Blocked, REPO

class RecoveryTests(unittest.TestCase):
    def test_get_recovery_and_bounded_failure(self):
        for error in [urllib.error.URLError(socket.gaierror()), TimeoutError(), ConnectionResetError(), ssl.SSLError(), http.client.IncompleteRead(b'partial'), urllib.error.HTTPError('secret',503,'secret',{},None)]:
            with self.subTest(error=type(error).__name__), patch('automation.dispatcher.audit') as audit, patch('automation.dispatcher.time.sleep'), patch('urllib.request.build_opener') as factory:
                opener=factory.return_value
                response=MagicMock();response.__enter__.return_value.read.return_value=b'{}'
                opener.open.side_effect=[error,response]
                self.assertEqual(GitHub('synthetic').api('GET',''),{})
                self.assertEqual(opener.open.call_count,2)
                opener.open.reset_mock();opener.open.side_effect=error
                with self.assertRaises(Blocked):GitHub('synthetic').api('GET','')
                self.assertEqual(opener.open.call_count,3)
                self.assertNotIn('synthetic',str(audit.call_args_list))

    def test_post_and_http_auth_do_not_retry(self):
        for method,route,error in [('POST','/issues/4/comments',TimeoutError()),('GET','',urllib.error.HTTPError('secret-url',401,'secret',{},None))]:
            with patch('automation.dispatcher.audit'),patch('urllib.request.build_opener') as factory:
                factory.return_value.open.side_effect=error
                with self.assertRaises(Blocked) as result:GitHub('synthetic').api(method,route,{'body':'sample'} if method=='POST' else None)
                self.assertEqual(factory.return_value.open.call_count,1)
                self.assertNotIn('secret',str(result.exception))

    def test_deadline_blocks_retry(self):
        with patch('automation.dispatcher.audit'),patch('urllib.request.build_opener') as factory,patch('automation.dispatcher.time.sleep') as sleep:
            factory.return_value.open.side_effect=TimeoutError()
            api=GitHub('synthetic');api.deadline=time.monotonic()+0.1
            with self.assertRaises(Blocked):api.api('GET','')
            self.assertEqual(factory.return_value.open.call_count,1);sleep.assert_not_called()

    def fixture(self):
        content=b'SAMPLE MODE\n';sha=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        entries=[{'path':name,'type':'blob','mode':'100644','size':len(content),'sha':sha} for name in ['a.md','b.md']]
        raw=b''.join(b'100644 '+e['path'].encode()+b'\0'+bytes.fromhex(sha) for e in entries)
        tree=hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest();commit='a'*40
        data={'':{'full_name':REPO,'private':False},'/git/ref/heads/main':{'object':{'sha':commit}},'/git/commits/'+commit:{'sha':commit,'tree':{'sha':tree}},'/git/trees/'+tree+'?recursive=1':{'sha':tree,'tree':entries},'/git/blobs/'+sha:{'sha':sha,'size':len(content),'encoding':'base64','content':base64.b64encode(content).decode()}}
        return data,sha

    def test_complete_hash_verified_and_deduplicated(self):
        data,sha=self.fixture();api=GitHub('synthetic')
        with tempfile.TemporaryDirectory() as d,patch.object(api,'api',side_effect=lambda m,r:data[r]) as request:
            api.snapshot(Path(d));self.assertEqual(len(list(Path(d).iterdir())),2)
            self.assertEqual(sum(c.args[1]=='/git/blobs/'+sha for c in request.call_args_list),1)

    def test_failure_never_materializes_partial_snapshot(self):
        for failure in ['network','partial_network','hash','size','path','repo','tree','commit','orphan']:
            data,sha=self.fixture();api=GitHub('synthetic')
            if failure=='hash':data['/git/blobs/'+sha]['content']=base64.b64encode(b'WRONG').decode()
            if failure=='size':data['/git/blobs/'+sha]['size']=0
            if failure=='repo':data['']['full_name']='other/repo'
            if failure=='commit':data['/git/commits/'+'a'*40]['sha']='b'*40
            tree=next(k for k in data if k.startswith('/git/trees/'))
            if failure=='partial_network':data[tree]['tree'][1]['sha']='b'*40
            if failure=='orphan':data[tree]['tree'].append({**data[tree]['tree'][0],'path':'absent/hidden.md'})
            if failure=='path':data[tree]['tree'][1]['path']='../escape'
            if failure=='tree':data[tree]['tree'][1]['mode']='100755'
            def get(method,route):
                if failure=='partial_network' and route=='/git/blobs/'+'b'*40:raise Blocked('network after first blob')
                if failure=='network' and route.startswith('/git/blobs/'):raise Blocked('network')
                return data[route]
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as d,patch.object(api,'api',side_effect=get):
                with self.assertRaises(Blocked):api.snapshot(Path(d))
                self.assertEqual(list(Path(d).iterdir()),[])
