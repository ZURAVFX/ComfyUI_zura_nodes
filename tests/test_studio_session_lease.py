"""Real scoped HTTP lease checks; no model, GPU or AE process."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from comfylink.studio_sessions import register,PREFIX,SESSION_HEADER,TOKEN_HEADER,TTL,MAX_LEASE_AGE

def iso(value):return datetime.fromtimestamp(value,timezone.utc).isoformat()

class SessionLeaseHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.clock=time.time();self.created=self.clock;self.maximum=self.clock+MAX_LEASE_AGE
        self.token='b'*64;self.broker_id='a'*32;self.renew_calls=0;self.grant_calls=0;self.leaves=0
        self.supported=True;self.reply_override={};self.renew_status=200;self.gate=None;self.entered=asyncio.Event()
        routes=web.RouteTableDef()
        @routes.get('/studio-bridge/{id}/grant')
        async def grant(request):
            self.assertEqual(request.headers.get(TOKEN_HEADER),self.token);self.grant_calls+=1
            return web.json_response({'schemaVersion':1,'id':self.broker_id,'comfyOrigin':self.origin,
                'expiresAt':iso(self.clock+1800),'target':{'label':'AE layer'},'source':{'width':1,'height':1,'frameCount':1},
                'capabilities':{'source':True,'transfer':True,**({'renew':True} if self.supported else {})}})
        @routes.post('/studio-bridge/{id}/renew')
        async def renew(request):
            self.assertEqual(request.headers.get(TOKEN_HEADER),self.token);self.assertEqual(await request.json(),{})
            self.renew_calls+=1;self.entered.set()
            if self.gate is not None:await self.gate.wait()
            if self.renew_status!=200:return web.json_response({'error':'retained'},status=self.renew_status)
            return web.json_response({'ok':True,'expiresAt':iso(min(self.clock+1800,self.maximum)),
                'maxExpiresAt':iso(self.maximum),'token':'never echo','personalPath':'never echo',**self.reply_override})
        @routes.post('/studio-bridge/{id}/leave')
        async def leave(request):self.leaves+=1;return web.json_response({'ok':True})
        broker=web.Application();broker.add_routes(routes)
        self.broker=TestServer(broker,host='127.0.0.1');await self.broker.start_server()
        self.broker_url=str(self.broker.make_url('/studio-bridge/'+self.broker_id))
        public_routes=web.RouteTableDef();server=types.SimpleNamespace(routes=public_routes)
        self.service=register(server,input_root=root/'input',output_root=root/'output')
        app=web.Application();app.add_routes(public_routes)
        self.client=TestClient(TestServer(app,host='127.0.0.1'));await self.client.start_server()
        self.origin=str(self.client.make_url('/')).rstrip('/')
        self.clock_patch=patch('comfylink.studio_sessions.time.time',side_effect=lambda:self.clock);self.clock_patch.start()
    async def asyncTearDown(self):
        if self.gate is not None:self.gate.set()
        for session in list(self.service.sessions.values()):self.service.close_local(session)
        if self.service._revocations:await asyncio.gather(*self.service._revocations,return_exceptions=True)
        self.clock_patch.stop();await self.client.close();await self.broker.close();self.temp.cleanup()
    async def create(self):
        response=await self.client.post(PREFIX+'/sessions',json={'broker':self.broker_url,'token':self.token})
        self.assertEqual(response.status,201,await response.text());data=await response.json()
        return data,{SESSION_HEADER:data['capability']}
    def route(self,session):return PREFIX+'/sessions/'+session['id']+'/renew'
    async def test_active_renewals_cross_original_deadline_without_replaying_grant(self):
        session,headers=await self.create();self.assertTrue(session['lease']['renewable'])
        for _ in range(4):
            self.clock+=600
            response=await self.client.post(self.route(session),json={},headers=headers)
            self.assertEqual(response.status,200,await response.text());reply=await response.json()
            self.assertEqual(set(reply),{'ok','expiresAt','maxExpiresAt'});self.assertNotIn('never echo',json.dumps(reply))
            self.assertAlmostEqual(self.service.sessions[session['id']].expires,self.clock+TTL,places=3)
            self.service.cleanup();self.assertIn(session['id'],self.service.sessions)
        self.assertGreater(self.clock,self.created+1800)
        replay=await self.client.post(PREFIX+'/sessions',json={'broker':self.broker_url,'token':self.token})
        self.assertEqual(replay.status,409);self.assertEqual(self.grant_calls,1)
        fingerprint=hashlib.sha256((self.broker_url+self.token).encode()).hexdigest()
        self.assertGreater(self.service.used[fingerprint],self.clock)
    async def test_renewal_is_not_blocked_by_source_or_result_lock(self):
        session,headers=await self.create();stored=self.service.sessions[session['id']]
        async with stored.lock:
            response=await asyncio.wait_for(self.client.post(self.route(session),json={},headers=headers),1)
            self.assertEqual(response.status,200)
    async def test_duplicate_concurrent_requests_share_one_broker_renewal(self):
        session,headers=await self.create();self.clock+=60;self.gate=asyncio.Event()
        first=asyncio.create_task(self.client.post(self.route(session),json={},headers=headers))
        await self.entered.wait()
        second=asyncio.create_task(self.client.post(self.route(session),json={},headers=headers))
        await asyncio.sleep(.01);self.gate.set()
        responses=await asyncio.gather(first,second)
        self.assertTrue(all(response.status==200 for response in responses));self.assertEqual(self.renew_calls,1)
    async def test_wrong_authority_origin_body_and_unsupported_broker(self):
        session,headers=await self.create()
        response=await self.client.post(self.route(session),json={},headers={SESSION_HEADER:'0'*64});self.assertEqual(response.status,403)
        response=await self.client.post(self.route(session),json={},headers={**headers,'Origin':'https://other.example'});self.assertEqual(response.status,403)
        for body in ({'hours':99},None,[]):
            response=await self.client.post(self.route(session),data=json.dumps(body),headers={**headers,'Content-Type':'application/json'})
            self.assertEqual(response.status,400)
        self.assertEqual(self.renew_calls,0)
        self.supported=False;old,old_headers=await self.create_distinct()
        response=await self.client.post(self.route(old),json={},headers=old_headers);self.assertEqual(response.status,409)
    async def create_distinct(self):
        # A separate valid registration is used only for compatibility tests.
        self.service.used.clear();return await self.create()
    async def test_expired_and_revoked_sessions_do_not_reach_broker(self):
        for revoked in (False,True):
            self.service.used.clear();session,headers=await self.create();stored=self.service.sessions[session['id']]
            if revoked:self.service.close_local(stored)
            else:self.clock=stored.expires+.01
            before=self.renew_calls;response=await self.client.post(self.route(session),json={},headers=headers)
            self.assertEqual(response.status,410);self.assertEqual(self.renew_calls,before)
    async def test_private_revocation_cleans_public_authority_but_keeps_files(self):
        session,headers=await self.create();stored=self.service.sessions[session['id']]
        retained=Path(self.temp.name)/'retained.exr';retained.write_bytes(b'original')
        self.renew_status=410
        response=await self.client.post(self.route(session),json={},headers=headers)
        self.assertEqual(response.status,410);self.assertTrue(stored.closed);self.assertEqual(stored.capability,'')
        self.assertNotIn(session['id'],self.service.sessions);self.assertEqual(retained.read_bytes(),b'original')
    async def test_busy_or_invalid_broker_reply_does_not_extend_lease(self):
        session,headers=await self.create();stored=self.service.sessions[session['id']];before=stored.expires
        self.renew_status=503
        response=await self.client.post(self.route(session),json={},headers=headers);self.assertEqual(response.status,502)
        self.assertEqual(stored.expires,before);self.assertFalse(stored.closed)
        self.renew_status=200
        for invalid in ({'expiresAt':iso(self.clock+7200)},{'maxExpiresAt':iso(self.clock+MAX_LEASE_AGE+60)},{'expiresAt':'invalid'},{'ok':False}):
            self.reply_override=invalid
            response=await self.client.post(self.route(session),json={},headers=headers);self.assertEqual(response.status,502)
            self.assertEqual(stored.expires,before)
    async def test_absolute_limit_and_leave_during_renewal_cannot_restore_authority(self):
        session,headers=await self.create();stored=self.service.sessions[session['id']]
        self.clock=stored.max_expires+1;stored.expires=self.clock+30
        response=await self.client.post(self.route(session),json={},headers=headers);self.assertEqual(response.status,410)
        self.service.close_local(stored);self.service.used.clear();self.clock=self.created
        session,headers=await self.create();stored=self.service.sessions[session['id']];self.gate=asyncio.Event();self.entered.clear()
        pending=asyncio.create_task(self.client.post(self.route(session),json={},headers=headers));await self.entered.wait()
        response=await self.client.post(PREFIX+'/sessions/'+session['id']+'/leave',json={},headers=headers)
        self.assertEqual(response.status,200);self.gate.set();reply=await pending
        self.assertEqual(reply.status,410);self.assertTrue(stored.closed);self.assertEqual(stored.capability,'')

if __name__=='__main__':unittest.main()
