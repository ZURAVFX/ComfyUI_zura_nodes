"""Single-window Desktop handoff. Scoped tokens are never broadcast."""
import asyncio
from dataclasses import dataclass, field
import hashlib
import re
import secrets
import time

import aiohttp
from aiohttp import web

from .studio_sessions import _bounded_json, _broker, _equal, _origin, _secret, TOKEN_HEADER

BASE = '/zura/comfylink/v1/studio/desktop'
CLIENT = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
HEX32 = re.compile(r'^[a-f0-9]{32}$')
TTL = 30


@dataclass
class Candidate:
    socket: object = field(repr=False)
    expires: float


@dataclass
class Handoff:
    request_id: str
    challenge: str = field(repr=False)
    broker: str = field(repr=False)
    token: str = field(repr=False)
    token_hash: str = field(repr=False)
    origin: str
    expires: float
    sockets: dict = field(default_factory=dict, repr=False)
    answers: dict = field(default_factory=dict)
    state: str = 'waiting'
    selected: tuple = None


class DesktopHandoff:
    def __init__(self, server):
        self.server = server
        self.clients = {}
        self.handoffs = {}
        self.lock = asyncio.Lock()

    def cleanup(self):
        now = time.time()
        for key, item in list(self.clients.items()):
            if item.expires <= now or getattr(item.socket, 'closed', True) or self._socket(key) is not item.socket:
                self.clients.pop(key, None)
        for key, item in list(self.handoffs.items()):
            if item.expires <= now:
                item.token = ''
                self.handoffs.pop(key, None)

    def _socket(self, client_id):
        return getattr(self.server, 'sockets', {}).get(client_id)

    def _current(self, item, client_id):
        socket = item.sockets.get(client_id)
        return socket is not None and not getattr(socket, 'closed', True) and self._socket(client_id) is socket

    def _authorise(self, request, request_id):
        origin = _origin(request)
        self.cleanup()
        if not isinstance(request_id, str) or not HEX32.fullmatch(request_id):
            raise web.HTTPBadRequest(text='Invalid Desktop handoff identity')
        item = self.handoffs.get(request_id)
        if item is None or item.origin != origin:
            raise web.HTTPGone(text='Desktop handoff is unavailable')
        supplied = request.headers.get(TOKEN_HEADER, '')
        if not _secret(supplied) or not _equal(hashlib.sha256(supplied.encode()).hexdigest(), item.token_hash):
            raise web.HTTPForbidden(text='Desktop handoff authentication failed')
        return item

    async def register(self, request):
        _origin(request)
        body = await _bounded_json(request.content, 4096)
        client_id = body.get('clientId') if isinstance(body, dict) else None
        if set(body) != {'clientId'} or not isinstance(client_id, str) or not CLIENT.fullmatch(client_id):
            raise web.HTTPBadRequest(text='Invalid Desktop client')
        self.cleanup()
        socket = self._socket(client_id)
        if socket is None or getattr(socket, 'closed', True):
            raise web.HTTPGone(text='Desktop connection is unavailable')
        if client_id not in self.clients and len(self.clients) >= 32:
            raise web.HTTPTooManyRequests(text='Too many Desktop candidates')
        self.clients[client_id] = Candidate(socket, time.time() + 45)
        return web.json_response({'ok': True}, headers={'Cache-Control': 'no-store'})

    async def challenge(self, request):
        origin = _origin(request)
        body = await _bounded_json(request.content, 4096)
        if not isinstance(body, dict) or set(body) != {'requestId', 'challenge', 'broker', 'token'}:
            raise web.HTTPBadRequest(text='Invalid Desktop handoff')
        request_id, challenge, token = body['requestId'], body['challenge'], body['token']
        broker = _broker(body['broker'])
        if not isinstance(request_id, str) or not HEX32.fullmatch(request_id) or not _secret(challenge) or not _secret(token):
            raise web.HTTPBadRequest(text='Invalid Desktop handoff identity')
        # The broker validates both scoped token and exact Comfy origin. Status
        # is non-consuming: the selected client still redeems the real grant.
        try:
            async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=5)) as client:
                async with client.get(broker + '/status', headers={TOKEN_HEADER: token, 'Origin': origin}, allow_redirects=False) as response:
                    if response.status != 200:
                        raise web.HTTPForbidden(text='Studio source authority is unavailable')
                    status = await _bounded_json(response.content, 4096)
                    if status.get('ready') is not True:
                        raise web.HTTPConflict(text='Studio source is not ready')
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise web.HTTPBadGateway(text='Studio broker is unavailable')
        async with self.lock:
            self.cleanup()
            if request_id in self.handoffs:
                raise web.HTTPConflict(text='Desktop handoff already exists')
            if len(self.handoffs) >= 32:
                raise web.HTTPTooManyRequests(text='Too many Desktop handoffs')
            sockets = {sid: item.socket for sid, item in self.clients.items() if item.expires > time.time() and self._socket(sid) is item.socket and not getattr(item.socket, 'closed', True)}
            if not sockets:
                raise web.HTTPNotFound(text='No open Comfy Desktop connection was found')
            item = Handoff(request_id, challenge, broker, token, hashlib.sha256(token.encode()).hexdigest(), origin, time.time() + TTL, sockets)
            self.handoffs[request_id] = item
            asyncio.get_running_loop().call_later(TTL + .1, self.cleanup)
        # The challenge is public random data. It contains neither broker URL
        # nor token, and is sent only to registered live candidate sockets.
        for sid, socket in sockets.items():
            if self._current(item, sid):
                try:
                    await asyncio.wait_for(socket.send_json({'type': 'comfylink-desktop-challenge', 'data': {'requestId': request_id, 'challenge': challenge}}), 2)
                except (asyncio.TimeoutError, ConnectionError, RuntimeError):
                    pass
        return web.json_response({'ok': True}, headers={'Cache-Control': 'no-store'})

    async def respond(self, request):
        origin = _origin(request)
        body = await _bounded_json(request.content, 4096)
        if not isinstance(body, dict) or set(body) != {'requestId', 'challenge', 'clientId', 'windowNonce'}:
            raise web.HTTPBadRequest(text='Invalid Desktop challenge response')
        if not isinstance(body['requestId'], str) or not HEX32.fullmatch(body['requestId']) or not _secret(body['challenge']):
            raise web.HTTPBadRequest(text='Invalid Desktop challenge identity')
        self.cleanup()
        item = self.handoffs.get(body['requestId'])
        client_id, nonce = body['clientId'], body['windowNonce']
        if item is None or item.origin != origin or item.state != 'waiting' or not _equal(body['challenge'], item.challenge) or not isinstance(client_id, str) or not CLIENT.fullmatch(client_id) or not isinstance(nonce, str) or not HEX32.fullmatch(nonce) or not self._current(item, client_id):
            raise web.HTTPForbidden(text='Desktop challenge response is unavailable')
        previous = item.answers.get(client_id)
        if previous is not None and previous != nonce:
            raise web.HTTPConflict(text='Desktop challenge already answered')
        if nonce in item.answers.values() and previous != nonce:
            raise web.HTTPConflict(text='Desktop window identity is ambiguous')
        item.answers[client_id] = nonce
        return web.json_response({'ok': True}, headers={'Cache-Control': 'no-store'})

    async def status(self, request):
        item = self._authorise(request, request.match_info.get('id', ''))
        candidates = [{'clientId': sid, 'windowNonce': nonce} for sid, nonce in item.answers.items() if self._current(item, sid)]
        return web.json_response({'state': item.state, 'candidates': candidates}, headers={'Cache-Control': 'no-store'})

    async def deliver(self, request):
        body = await _bounded_json(request.content, 4096)
        if not isinstance(body, dict) or set(body) != {'requestId', 'clientId', 'windowNonce'}:
            raise web.HTTPBadRequest(text='Invalid Desktop delivery')
        item = self._authorise(request, body['requestId'])
        async with self.lock:
            sid, nonce = body['clientId'], body['windowNonce']
            if self.handoffs.get(item.request_id) is not item or item.expires <= time.time() or item.state != 'waiting' or item.answers.get(sid) != nonce or not self._current(item, sid):
                raise web.HTTPConflict(text='The verified Desktop connection changed')
            socket = item.sockets[sid]
            item.state = 'delivered'
            item.selected = (sid, nonce)
            credential = {'requestId': item.request_id, 'challenge': item.challenge, 'windowNonce': nonce, 'broker': item.broker, 'token': item.token}
            item.token = ''
        try:
            await asyncio.wait_for(socket.send_json({'type': 'comfylink-desktop-handoff', 'data': credential}), 5)
        except (asyncio.TimeoutError, ConnectionError, RuntimeError):
            raise web.HTTPBadGateway(text='Desktop delivery outcome is uncertain')
        finally:
            credential['token'] = ''
        return web.json_response({'ok': True, 'state': 'delivered'}, headers={'Cache-Control': 'no-store'})

    async def acknowledge(self, request):
        origin = _origin(request)
        body = await _bounded_json(request.content, 4096)
        if not isinstance(body, dict) or set(body) != {'requestId', 'challenge', 'clientId', 'windowNonce', 'accepted'} or type(body['accepted']) is not bool:
            raise web.HTTPBadRequest(text='Invalid Desktop acknowledgement')
        if not isinstance(body['requestId'], str) or not HEX32.fullmatch(body['requestId']) or not _secret(body['challenge']) or not isinstance(body['clientId'], str) or not CLIENT.fullmatch(body['clientId']) or not isinstance(body['windowNonce'], str) or not HEX32.fullmatch(body['windowNonce']):
            raise web.HTTPBadRequest(text='Invalid Desktop acknowledgement identity')
        self.cleanup()
        item = self.handoffs.get(body['requestId'])
        if item is None or item.origin != origin or item.state != 'delivered' or not _equal(body['challenge'], item.challenge) or item.selected != (body['clientId'], body['windowNonce']) or not self._current(item, body['clientId']):
            raise web.HTTPForbidden(text='Desktop acknowledgement is unavailable')
        item.state = 'accepted' if body['accepted'] else 'rejected'
        return web.json_response({'ok': True}, headers={'Cache-Control': 'no-store'})

    async def cancel(self, request):
        body = await _bounded_json(request.content, 4096)
        if not isinstance(body, dict) or set(body) != {'requestId'}:
            raise web.HTTPBadRequest(text='Invalid Desktop cancellation')
        item = self._authorise(request, body['requestId'])
        item.token = ''
        item.state = 'cancelled'
        for sid, socket in item.sockets.items():
            if self._current(item, sid):
                try:
                    await asyncio.wait_for(socket.send_json({'type': 'comfylink-desktop-finished', 'data': {'requestId': item.request_id}}), 2)
                except (asyncio.TimeoutError, ConnectionError, RuntimeError):
                    pass
        return web.json_response({'ok': True}, headers={'Cache-Control': 'no-store'})


def register(server):
    service = DesktopHandoff(server)
    server.routes.post(BASE + '/register')(service.register)
    server.routes.post(BASE + '/challenge')(service.challenge)
    server.routes.post(BASE + '/respond')(service.respond)
    server.routes.get(BASE + '/status/{id}')(service.status)
    server.routes.post(BASE + '/deliver')(service.deliver)
    server.routes.post(BASE + '/ack')(service.acknowledge)
    server.routes.post(BASE + '/cancel')(service.cancel)
    return service
