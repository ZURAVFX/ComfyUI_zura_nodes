"""Account routes: no real profile, credentials, network or model access."""
import importlib
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch
from aiohttp import web
import v2_bootstrap

routes_module = importlib.import_module('ComfyUI_zura_nodes.browser_image_routes')


class BrowserRoutesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        routes = web.RouteTableDef()
        routes_module.register(routes)
        self.routes = {route.path: route.handler for route in routes}
        self.sessions = types.ModuleType('ComfyUI_zura_nodes.web_sessions')
        self.sessions.start_login = Mock()
        self.sessions.login_status = Mock(return_value={'state': 'disconnected', 'message': 'Connect'})
        self.modules = patch.dict(sys.modules, {self.sessions.__name__: self.sessions})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def request(self, data=None, headers=None):
        async def body():
            return data
        return types.SimpleNamespace(host='127.0.0.1:8188', headers=headers or {},
                                     query={'provider': 'gemini'}, json=body)

    async def test_only_explicit_login_starts_session_access(self):
        response = await self.routes['/zura/browser_image_status'](self.request())
        self.assertEqual(json.loads(response.body)['state'], 'disconnected')
        self.sessions.start_login.assert_not_called()
        response = await self.routes['/zura/browser_image_login'](self.request({'provider': 'gemini'}))
        self.assertEqual(response.status, 200)
        self.sessions.start_login.assert_called_once_with('gemini')

    async def test_cross_site_requests_never_touch_session_state(self):
        for handler in self.routes.values():
            for headers in ({'Origin': 'https://other.example'}, {'Sec-Fetch-Site': 'cross-site'}):
                with self.assertRaises(web.HTTPForbidden):
                    await handler(self.request({'provider': 'gemini'}, headers))
        self.sessions.start_login.assert_not_called()
        self.sessions.login_status.assert_not_called()

    async def test_invalid_request_is_reported_without_session_access(self):
        response = await self.routes['/zura/browser_image_login'](self.request(['gemini']))
        self.assertEqual(response.status, 400)
        self.sessions.start_login.assert_not_called()
        self.sessions.start_login.side_effect = ValueError('Unknown image provider.')
        response = await self.routes['/zura/browser_image_login'](self.request({'provider': 'unknown'}))
        self.assertEqual(response.status, 400)


if __name__ == '__main__':
    unittest.main()
