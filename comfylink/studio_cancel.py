"""Cancellation follows authenticated AE work, never the global Comfy queue."""
import asyncio
import contextvars
import inspect
import re
import time

from aiohttp import web

SESSION_ID_HEADER = 'X-ComfyLink-Studio-Id'
_current = contextvars.ContextVar('comfylink_ae_work', default=None)
_TAG = 'zura_comfylink_session'


def broker_ended(response):
    status = response.get('status')
    return status in {'cancelled', 'closed', 'expired', 'left'} or (response.get('ready') is False and status not in {'preparing', 'ready', 'import_pending', 'sent'})


class SessionWork:
    def __init__(self, service, server):
        self.service, self.server = service, server
        self.claims = {}
        self.owners = {kind: {} for kind in ('project', 'hdr', 'outpaint')}
        self.project_owners = self.owners['project']
        self.tasks = set()
        queue = getattr(server, 'prompt_queue', None)
        if queue is not None and callable(getattr(queue, 'put', None)):
            original = queue.put

            def put(item):
                scope = _current.get()
                identity = item[3].get(_TAG) if len(item) > 3 and isinstance(item[3], dict) else None
                session = scope[1] if scope and scope[0] is self else None
                if session is not None:
                    identity = session.id
                # The queue mutex also protects the running-job identity used
                # by cancellation. No global interrupt flag is set here.
                with queue.mutex:
                    if session is not None and session.closed:
                        raise ValueError('This AE shot was cancelled; send the shot again from After Effects')
                    if identity and (identity not in self.claims or self.claims[identity]['closed']):
                        raise ValueError('This AE shot was cancelled; its continuation was stopped')
                    if session is not None:
                        values = list(item)
                        values[3] = {**values[3], _TAG: identity}
                        item = tuple(values)
                    if identity:
                        self.claims[identity]['prompts'].add(item[1])
                    return original(item)
            queue.put = put

    def record(self, session):
        now = time.time()
        for identity, old in list(self.claims.items()):
            if old['closed'] and old['expires'] <= now and (old.get('task') is None or old['task'].done()):
                self.claims.pop(identity, None)
                for owners in self.owners.values():
                    for key, owner in list(owners.items()):
                        if owner == identity:
                            owners.pop(key, None)
        return self.claims.setdefault(session.id, {'closed': False, 'callbacks': {}, 'prompts': set(), 'expires': session.created_at + 28800})

    def watch(self, session, delay=1):
        """Host Cancel must work even while the browser is hidden or suspended."""
        async def poll():
            while not session.closed and self.service.sessions.get(session.id) is session:
                await asyncio.sleep(delay)
                if session.closed:
                    return
                try:
                    response = await self.service.broker_json(session, '/status')
                    ended = broker_ended(response)
                    if response.get('status') == 'sent':
                        return
                except web.HTTPGone:
                    ended = True
                except (web.HTTPException, ConnectionError, asyncio.TimeoutError):
                    continue
                if ended:
                    authority = self.service.close_local(session)
                    await self.cancel(session)
                    if authority is not None:
                        await self.service.revoke_broker(authority)
                    return
        task = asyncio.get_running_loop().create_task(poll())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    @web.middleware
    async def middleware(self, request, handler):
        identity = request.headers.get(SESSION_ID_HEADER)
        # Comfy mirrors its legacy routes beneath /api. Apply the same ingress
        # and cancellation policy to both spellings, including query strings.
        path = request.path
        while path.startswith('/api/'):
            path = path[4:]
        if identity is None:
            if request.method == 'POST' and path == '/prompt':
                body = await request.json()
                extra = body.get('extra_data') if isinstance(body, dict) else None
                if isinstance(extra, dict) and _TAG in extra:
                    raise web.HTTPForbidden(text='AE ownership metadata requires an authenticated session')
            return await handler(request)
        # A capability is checked before any endpoint can prepare or submit
        # work. A plain graph/session ID never grants cancellation authority.
        from .studio_sessions import SESSION_HEADER, _equal, _origin
        session = self.service.sessions.get(identity)
        if session is None or session.closed:
            raise web.HTTPGone(text='This AE shot has ended')
        if session.origin != _origin(request) or not _equal(request.headers.get(SESSION_HEADER), session.capability):
            raise web.HTTPForbidden(text='AE work authentication failed')
        self.service.active(session)
        record = self.record(session)
        if request.method == 'POST':
            for kind, pattern in [('project', r'/(?:zura|genj)/studio/projects/([^/]+)(?:/.*)?'),
                                  ('hdr', r'/(?:zura|genj)/studio/hdr/jobs/([^/]+)(?:/.*)?'),
                                  ('outpaint', r'/(?:zura|genj)/studio/outpaint/jobs/([^/]+)(?:/.*)?')]:
                matched = re.fullmatch(pattern, path)
                if matched and self.owners[kind].get(matched[1]) != identity:
                    raise web.HTTPForbidden(text='This coordinator does not belong to the current AE shot')
            if path.startswith('/jobs/'):
                raise web.HTTPForbidden(text='Use this AE shot\'s scoped cancellation control')
        if request.method == 'POST' and path in {'/queue', '/interrupt'}:
            body = await request.json()
            ids = body.get('delete') if path == '/queue' else [body.get('prompt_id')]
            expected = {'delete'} if path == '/queue' else {'prompt_id'}
            if set(body) != expected or not isinstance(ids, list) or not ids or any(not isinstance(value, str) or value not in record['prompts'] for value in ids):
                raise web.HTTPForbidden(text='AE cancellation requires this shot\'s exact owned prompt')
        token = _current.set((self, session))
        try:
            return await handler(request)
        finally:
            _current.reset(token)

    def claim(self, key, cancel):
        """Called at coordinator creation while its authenticated scope is bound."""
        scope = _current.get()
        if not scope or scope[0] is not self:
            return
        session = scope[1]
        record = self.record(session)
        record['callbacks'][key] = cancel
        if isinstance(key, tuple) and len(key) == 2 and key[0] in self.owners:
            self.owners[key[0]][key[1]] = session.id
        if session.closed or record['closed']:
            self.schedule(session)
        return session.id

    def schedule(self, session):
        record = self.record(session)
        record['closed'] = True
        if record.get('task') is not None and not record['task'].done():
            return record['task']
        try:
            task = asyncio.get_running_loop().create_task(self._cancel(session, record))
            record['task'] = task
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            return task
        except RuntimeError:
            pass

    async def cancel(self, session):
        task = self.schedule(session)
        if task is not None:
            await asyncio.shield(task)

    async def _cancel(self, session, record):
        interrupted = set()
        self.drain_queue(session.id, interrupted)
        while record['callbacks']:
            callbacks = list(record['callbacks'].values())
            record['callbacks'].clear()
            for callback in callbacks:
                try:
                    result = callback()
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    # Completed outputs are never deleted even if a
                    # coordinator has already completed or disappeared.
                    pass
        self.drain_queue(session.id, interrupted)

    def drain_queue(self, identity, interrupted):
        queue = getattr(self.server, 'prompt_queue', None)
        if queue is None:
            return
        with queue.mutex:
            running, pending = queue.get_current_queue_volatile()
            owned = lambda item: len(item) > 3 and isinstance(item[3], dict) and item[3].get(_TAG) == identity
            for item in running:
                if owned(item) and item[1] not in interrupted:
                    queue.interrupt_if_running(item[1])
                    interrupted.add(item[1])
            while queue.delete_queue_item(owned):
                pass


def claim_work(server, key, cancel):
    service = getattr(server, '_zura_comfylink_studio_sessions', None)
    work = getattr(service, 'work', None)
    if work is not None:
        return work.claim(key, cancel)


def claim_project(studio, project):
    async def cancel():
        async with studio.lock:
            current = studio.store.load(project['id'])
            if current.get('_comfylink_session') != project.get('_comfylink_session'):
                return
            active = {'waiting', 'submitting', 'queued', 'running', 'interrupted'}
            for action in current.get('actions', []):
                if action.get('state') in active:
                    action['state'] = 'cancelled'
            if current.get('phase') == 'working':
                current.update(phase='error', error='AE shot cancelled. Completed results are retained.')
                studio.store.save(current)
    identity = claim_work(studio.server, ('project', project['id']), cancel)
    if identity:
        project['_comfylink_session'] = identity


def project_extra(server, project):
    identity = project.get('_comfylink_session')
    if not identity:
        return {}
    service = getattr(server, '_zura_comfylink_studio_sessions', None)
    record = getattr(getattr(service, 'work', None), 'claims', {}).get(identity)
    if record is None or record['closed']:
        raise ValueError('This AE shot has ended; its continuation was stopped')
    return {_TAG: identity}
