"""AE transfer choice is broker authority, independent of project bit depth."""
from datetime import datetime, timedelta, timezone
import importlib
import unittest

from aiohttp import web
import v2_bootstrap  # noqa: F401

studio = importlib.import_module('ComfyUI_zura_nodes.comfylink.studio_sessions')


class TransferGrantTests(unittest.TestCase):
    def test_exact_transfer_enum(self):
        identity='a'*32
        origin='http://127.0.0.1:8188'
        grant={'schemaVersion':1,'id':identity,'comfyOrigin':origin,
               'target':{'label':'AE test'},'capabilities':{'source':True,'transfer':True},
               'expiresAt':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),
               'source':{'width':512,'height':320,'frameCount':1}}
        broker=origin+'/studio/'+identity
        for transfer in ('sdr8','prores12','float32'):
            context,_=studio._grant({**grant,'transferPrecision':transfer},origin,broker)
            self.assertEqual(context['transferPrecision'],transfer)
            self.assertEqual(context['source']['width'],512)
        with self.assertRaises(web.HTTPBadGateway):
            studio._grant({**grant,'transferPrecision':'32'},origin,broker)
        still={**grant,'transferPrecision':'prores12','capabilities':{**grant['capabilities'],'nativeStillReturn':True}}
        context,_=studio._grant(still,origin,broker)
        self.assertIs(context['capabilities']['nativeStillReturn'],True)
        with self.assertRaises(web.HTTPBadGateway):
            studio._grant({**still,'capabilities':{**still['capabilities'],'nativeStillReturn':'true'}},origin,broker)
        legacy,_=studio._grant(grant,origin,broker)
        self.assertNotIn('transferPrecision',legacy)


if __name__=='__main__': unittest.main()
