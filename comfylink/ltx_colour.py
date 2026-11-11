"""Explicit scene-linear / LTX ACEScct bridge; no inference is hidden here.

Rec.709 D65 to ACEScg AP1 D60 uses the same Rec.709->Rec.2020 and
Bradford-adapted Rec.2020->AP1 matrices as ComfyUI nodes_images.py.
The ACEScct curve follows ACES S-2016-001. Model outputs may alter imagery.
"""
import copy
import torch

_R709_TO_2020 = ((.6274038959346991,.3292830383778837,.0433130656874172),(.0690972893582320,.9195403950754587,.0113623155663092),(.0163914388751503,.0880133078772259,.8955952532476238))
_R2020_TO_AP1 = ((.9748949779244186,.0195991086370050,.0055059134385761),(.0021795627977041,.9955354688932213,.0022849683090752),(.0047972396837727,.0245320166345895,.9706707436816380))


def _validate(images, metadata, encoding):
    if not isinstance(images, torch.Tensor) or images.dtype != torch.float32 or images.ndim != 4 or images.shape[-1] != 3 or images.numel() == 0 or not torch.isfinite(images).all():
        raise ValueError('Expected nonempty finite float32 NHWC RGB frames')
    if not isinstance(metadata, dict) or not isinstance(metadata.get('manifest'), dict):
        raise ValueError('Declared ComfyLink frame metadata is required')
    manifest = metadata['manifest']
    colour = manifest.get('colour')
    if not isinstance(colour, dict) or colour.get('encoding') not in encoding or colour.get('sceneLinear') != (colour.get('encoding') != 'acescct'):
        raise ValueError('Unsupported or inconsistent colour declaration')
    if 'profileSha256' in colour:
        raise ValueError('Custom profile conversion is not supported by this bridge')
    if manifest.get('alphaAssociation') != 'straight':
        raise ValueError('Unpremultiply input explicitly before colour conversion')
    alpha = metadata.get('original_alpha')
    if not isinstance(alpha, torch.Tensor) or alpha.dtype != torch.float32 or tuple(alpha.shape) != tuple(images.shape[:3]) or not torch.isfinite(alpha).all():
        raise ValueError('Matching finite alpha metadata is required')
    return colour['encoding']


def _metadata(metadata, colour, operation):
    result = copy.deepcopy(metadata)
    result['manifest']['colour'] = colour
    result.setdefault('transformations', []).append(operation)
    return result


def _policy(values, policy, operation):
    if policy not in ('reject', 'clamp'):
        raise ValueError('Choose reject or clamp range policy')
    low = int((values < 0).sum().item()); high = int((values > 1).sum().item())
    report = {'operation': operation, 'rangePolicy': policy, 'codeMin': float(values.min()), 'codeMax': float(values.max()), 'belowZeroCount': low, 'aboveOneCount': high}
    if (low or high) and policy == 'reject':
        raise ValueError('ACEScct codes fall outside [0, 1]; choose explicit clamp to discard range')
    return values.clamp(0, 1) if policy == 'clamp' else values, report


class ZuraComfyLinkToLTXColour:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',), 'frame_metadata': ('COMFYLINK_FRAME_METADATA',), 'range_policy': (['reject', 'clamp'], {'default': 'reject'})}}
    RETURN_TYPES = ('IMAGE', 'COMFYLINK_FRAME_METADATA')
    RETURN_NAMES = ('acescct_images', 'frame_metadata')
    FUNCTION = 'convert'
    CATEGORY = 'ComfyLink/High Depth'
    DESCRIPTION = 'Convert declared scene-linear Rec.709 or ACEScg to LTX ACEScct. Reject out-of-range codes by default. LTX model nodes remain separate.'
    def convert(self, images, frame_metadata, range_policy='reject'):
        encoding = _validate(images, frame_metadata, {'scene_linear_rec709', 'acescg'})
        x = images.to(torch.float64)
        if encoding == 'scene_linear_rec709':
            matrix = torch.tensor(_R2020_TO_AP1, dtype=x.dtype, device=x.device) @ torch.tensor(_R709_TO_2020, dtype=x.dtype, device=x.device)
            x = x @ matrix.T
        codes = torch.where(x > .0078125, (torch.log2(x.clamp(min=1e-38)) + 9.72) / 17.52, 10.5402377416545*x + .0729055341958355)
        codes, report = _policy(codes, range_policy, 'scene_linear_to_ltx_acescct')
        return codes.to(torch.float32), _metadata(frame_metadata, {'encoding': 'acescct', 'sceneLinear': False}, report)


class ZuraComfyLinkFromLTXColour:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',), 'frame_metadata': ('COMFYLINK_FRAME_METADATA',), 'range_policy': (['reject', 'clamp'], {'default': 'reject'})}}
    RETURN_TYPES = ('IMAGE', 'COMFYLINK_FRAME_METADATA')
    RETURN_NAMES = ('acescg_images', 'frame_metadata')
    FUNCTION = 'convert'
    CATEGORY = 'ComfyLink/High Depth'
    DESCRIPTION = 'Decode declared LTX ACEScct to scene-linear ACEScg float32; no additional highlight clamp or half quantisation.'
    def convert(self, images, frame_metadata, range_policy='reject'):
        _validate(images, frame_metadata, {'acescct'})
        x, report = _policy(images, range_policy, 'ltx_acescct_to_scene_linear')
        linear = torch.where(x > .155251141552511, torch.pow(2., x*17.52-9.72), (x-.0729055341958355)/10.5402377416545)
        if not torch.isfinite(linear).all(): raise ValueError('ACEScct decode produced nonfinite samples')
        return linear, _metadata(frame_metadata, {'encoding': 'acescg', 'sceneLinear': True}, report)

NODE_CLASS_MAPPINGS = {'ZuraComfyLinkToLTXColour': ZuraComfyLinkToLTXColour, 'ZuraComfyLinkFromLTXColour': ZuraComfyLinkFromLTXColour}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraComfyLinkToLTXColour': 'Zura ComfyLink to LTX Colour', 'ZuraComfyLinkFromLTXColour': 'Zura ComfyLink from LTX Colour'}
