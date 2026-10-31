"""Experimental split of the outpaint prompt encoder from video inference.

The caller must run the returned text graph, safely release its text model,
then run the video graph. This module does not unload shared ComfyUI models.
"""
import copy
import re


def split_prompt_graph(graph, cache_key):
    if not isinstance(cache_key, str) or not re.fullmatch(r'[a-f0-9]{64}', cache_key):
        raise ValueError('Choose a valid private text cache key.')
    if not isinstance(graph, dict):
        raise ValueError('Choose an outpaint graph.')
    graph = copy.deepcopy(graph)
    encoder, positive, negative, conditioning = (graph.get(k) for k in ('encoder', 'positive', 'negative', 'conditioning'))
    if (not all(isinstance(n, dict) for n in (encoder, positive, negative, conditioning)) or
            encoder.get('class_type') != 'CLIPLoader' or
            positive.get('class_type') != 'CLIPTextEncode' or negative.get('class_type') != 'CLIPTextEncode' or
            positive.get('inputs', {}).get('clip') != ['encoder', 0] or
            negative.get('inputs', {}).get('clip') != ['encoder', 0] or
            conditioning.get('inputs', {}).get('positive') != ['positive', 0] or
            conditioning.get('inputs', {}).get('negative') != ['negative', 0]):
        raise ValueError('The outpaint prompt graph does not match the supported layout.')
    for key, node in graph.items():
        if key in ('encoder', 'positive', 'negative', 'conditioning'):
            continue
        for value in node.get('inputs', {}).values():
            if isinstance(value, list) and len(value) == 2 and value[0] in ('encoder', 'positive', 'negative'):
                raise ValueError('The prompt encoder has unexpected consumers.')
    text = {key: graph.pop(key) for key in ('encoder', 'positive', 'negative')}
    text['save_text'] = {'class_type': 'GenjSaveTextConditioning', 'inputs': {
        'positive': ['positive', 0], 'negative': ['negative', 0], 'cache_key': cache_key}}
    graph['load_text'] = {'class_type': 'GenjLoadTextConditioning', 'inputs': {'cache_key': cache_key}}
    graph['conditioning']['inputs'].update(positive=['load_text', 0], negative=['load_text', 1])
    return text, graph
