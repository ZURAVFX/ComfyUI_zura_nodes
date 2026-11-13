"""CPU bridge used by the JavaScript-to-real-camera-planner regression."""
import importlib,json,sys,types
from pathlib import Path

root=Path(sys.argv[1]).resolve()
for name,path in [('ComfyUI_zura_nodes',root),('ComfyUI_zura_nodes.artist_studio',root/'artist_studio')]:
    module=types.ModuleType(name);module.__path__=[str(path)];sys.modules[name]=module
camera=importlib.import_module('ComfyUI_zura_nodes.artist_studio.panorama_camera')
body=json.load(sys.stdin)
try:
    selected=camera.plan(body['source'],body['config'])
    graph=camera.build_graph(body['source'],selected,None,'render',warp='fixture-warp.mp4')
    prepared=graph
    if selected.get('ae_frame_contract'):
        from ComfyUI_zura_nodes.comfylink.frame_contract import prepare_frame_contract_graph
        prepared=prepare_frame_contract_graph(graph,selected['ae_frame_contract'],'camera')
    clock=json.loads(camera.camera_state(None,selected))['timeline']
    print(json.dumps({'ok':True,'frames':selected['frames'],'fps':selected['fps'],'duration':selected['duration'],
                     'contract':selected.get('ae_frame_contract'),'timeline':clock,
                     'conditioningFPS':graph['conditioning']['inputs']['frame_rate'],
                     'audioFPS':graph['empty_audio']['inputs']['frame_rate'],
                     'videoFPS':graph['video']['inputs']['fps'],'trimFrames':graph['trim']['inputs']['length'],
                     'paddedFrames':selected['padded'],
                     'preparedLatentLengths':[n['inputs']['length'] for n in prepared.values() if n['class_type']=='EmptyLTXVLatentVideo'],
                     'preparedFrameGuards':[n['inputs']['frame_count'] for n in prepared.values() if n['class_type']=='ZuraComfyLinkMatchFrames']}))
except ValueError as error:
    print(json.dumps({'ok':False,'error':str(error)}))
