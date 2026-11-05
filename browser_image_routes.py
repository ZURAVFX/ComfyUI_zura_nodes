"""Same-origin controls for the existing website-account image nodes."""
from aiohttp import web
from .media_source import require_same_origin


def register(routes):
    @routes.post('/zura/browser_image_login')
    async def login(request):
        require_same_origin(request)
        from .web_sessions import start_login
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError('Choose ChatGPT or Gemini.')
            start_login(str(data.get('provider', '')), data.get('browser'))
            return web.json_response({'ok': True}, headers={'Cache-Control': 'no-store'})
        except (ValueError, RuntimeError) as error:
            return web.json_response({'error': str(error)}, status=400)

    @routes.post('/zura/browser_image_cancel')
    async def cancel(request):
        require_same_origin(request)
        from .web_sessions import cancel_login
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError('Choose ChatGPT or Gemini.')
            cancel_login(str(data.get('provider', '')))
            return web.json_response({'ok': True}, headers={'Cache-Control': 'no-store'})
        except (ValueError, RuntimeError) as error:
            return web.json_response({'error': str(error)}, status=400)

    @routes.get('/zura/browser_image_status')
    async def status(request):
        require_same_origin(request)
        from .web_sessions import login_status
        try:
            return web.json_response(login_status(str(request.query.get('provider', ''))), headers={'Cache-Control': 'no-store'})
        except (ValueError, RuntimeError) as error:
            return web.json_response({'error': str(error)}, status=400)
