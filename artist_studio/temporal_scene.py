"""Joint-view camera registration and persistent scenery for the native editor.

DA3 does inference in visible native nodes. These CPU adapters align overlapping
solves, fuse static surfaces and retain each frame's moving foreground. The
shared-scene design follows Reshoot 4D; it does not require its human-only rig or
trained splat. Coordinates stay in the first source camera until native MESH
delivery converts OpenCV to glTF once.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import torch


def windows(count, size=12, overlap=3):
    if count < 2 or not 1 <= overlap < size:
        raise ValueError('Scene reconstruction needs at least two frames and overlapping views.')
    result, start = [], 0
    while start < count:
        end = min(count, start + size)
        result.append((start, end))
        if end == count:
            break
        start = end - overlap
    return result


def unproject(depth, intrinsics):
    height, width = depth.shape[-2:]
    y, x = np.mgrid[:height, :width]
    pixels = np.stack([x, y, np.ones_like(x)], -1)
    return np.einsum('ij,hwj->hwi', np.linalg.inv(intrinsics), pixels) * depth[..., None]


def fit_similarity(source, target):
    """Robust, proper Sim(3); overlap is the SAME source frames, never motion."""
    a, b = np.asarray(source, np.float64), np.asarray(target, np.float64)
    valid = np.isfinite(a).all(1) & np.isfinite(b).all(1)
    a, b = a[valid], b[valid]
    if len(a) < 24:
        raise ValueError('Not enough reliable overlap to register the scene.')
    keep = np.ones(len(a), bool)
    for _ in range(3):
        aa, bb = a[keep], b[keep]
        ac, bc = aa.mean(0), bb.mean(0)
        x, y = aa - ac, bb - bc
        u, singular, vt = np.linalg.svd(y.T @ x / len(x))
        signs = np.ones(3)
        signs[-1] = np.sign(np.linalg.det(u @ vt))
        rotation = u @ np.diag(signs) @ vt
        scale = float((singular * signs).sum() / max(np.mean(np.sum(x*x, 1)), 1e-12))
        translation = bc - scale * (rotation @ ac)
        residual = np.linalg.norm(a @ rotation.T * scale + translation - b, axis=1)
        keep = residual <= max(float(np.quantile(residual, .8)), 1e-7)
    scene_size = max(float(np.median(np.linalg.norm(b, axis=1))), 1e-5)
    error = float(np.median(residual)) / scene_size
    if not .01 < scale < 100 or not np.isfinite(error) or error > .15:
        raise ValueError('The overlapping scene solves disagree. Shorten the clip or trim at a shot cut.')
    return scale, rotation, translation, error


def append_views(geometry, start_frame, previous=None, lock_camera=False):
    if geometry.get('mode') != 'multiview':
        raise ValueError('Use DA3 multi-view inference, not independent image depth.')
    arrays = {key: value.detach().cpu().numpy() for key, value in geometry.items() if isinstance(value, torch.Tensor)}
    depth, images = arrays['depth'], arrays['image']
    count, height, width = depth.shape
    extrinsics, intrinsics = arrays.get('extrinsics'), arrays.get('intrinsics')
    if extrinsics is None or intrinsics is None or intrinsics.shape != (1, count, 3, 3):
        raise ValueError('DA3 did not return a calibrated source-camera solve.')
    intrinsics = intrinsics[0].astype(np.float64)
    if not np.isfinite(intrinsics).all() or np.any(intrinsics[:, [0, 1], [0, 1]] <= 1):
        raise ValueError('The depth model did not estimate valid camera intrinsics.')
    # A clip has one source lens. Independent focal estimates otherwise create
    # breathing even though depth came from a joint solve. Match Reshoot's
    # square-pixel calibration, then keep it shared across solve windows.
    if previous is not None:
        reference_k = previous['reference_intrinsics'][0]
    else:
        reference_k = np.median(intrinsics, axis=0)
        focal = float(np.median(np.sqrt(intrinsics[:, 0, 0] * intrinsics[:, 1, 1])))
        reference_k[0, 0] = reference_k[1, 1] = focal
    intrinsics = np.repeat(reference_k[None], count, 0)
    world_to_camera = np.repeat(np.eye(4)[None], count, 0)
    world_to_camera[:, :3, :4] = extrinsics[0, :, :3, :4]
    if not np.isfinite(world_to_camera).all():
        raise ValueError('The source camera solve contains invalid poses.')
    poses = np.linalg.inv(world_to_camera)
    if lock_camera:
        poses[:] = np.eye(4)
        world_to_camera[:] = np.eye(4)
    points = np.stack([unproject(depth[i], intrinsics[i]) @ poses[i, :3, :3].T + poses[i, :3, 3] for i in range(count)])
    if previous is None:
        if start_frame != 0:
            raise ValueError('The first shared solve must begin at frame zero.')
        scale, rotation, translation, error = 1., world_to_camera[0, :3, :3], world_to_camera[0, :3, 3], 0.
        packet = {'points': [], 'depth': [], 'image': [], 'intrinsics': [], 'poses': [], 'alignment_errors': [],
                  'reference_intrinsics': [reference_k], 'camera_locked': [bool(lock_camera)]}
    else:
        packet = {key: list(value) for key, value in previous.items()}
        overlap = min(len(packet['points']) - start_frame, count)
        if overlap < 2 or start_frame < 0:
            raise ValueError('Camera solves need at least two shared frames.')
        source, target = [], []
        for index in range(overlap):
            if not np.allclose(images[index], packet['image'][start_frame+index], atol=1e-5, rtol=0):
                raise ValueError('Overlapping solves must refer to the same source frames.')
            a, b = points[index].reshape(-1, 3), packet['points'][start_frame + index].reshape(-1, 3)
            good = np.isfinite(a).all(1) & np.isfinite(b).all(1)
            good &= depth[index].reshape(-1) > 0
            ids = np.flatnonzero(good)[::max(1, int(good.sum()) // 2048)]
            source.append(a[ids]); target.append(b[ids])
        if lock_camera:
            ratios = []
            for index in range(overlap):
                a, b = depth[index], packet['depth'][start_frame+index]
                valid = np.isfinite(a) & np.isfinite(b) & (a > 0) & (b > 0)
                ratios.append((b[valid]/a[valid])[::16])
            scale, rotation, translation = float(np.median(np.concatenate(ratios))), np.eye(3), np.zeros(3)
            error = float(np.median(np.linalg.norm(np.concatenate(source)*scale-np.concatenate(target), axis=1))) / max(float(np.median(np.concatenate(ratios))), 1e-5)
        else:
            scale, rotation, translation, error = fit_similarity(np.concatenate(source), np.concatenate(target))
    points = (points @ rotation.T * scale + translation).astype(np.float32)
    poses[:, :3, :3] = rotation @ poses[:, :3, :3]
    poses[:, :3, 3] = poses[:, :3, 3] @ rotation.T * scale + translation
    packet['alignment_errors'].append(error)
    for index in range(count):
        at = start_frame + index
        if at < len(packet['points']):
            # Same-time estimates only: no averaging of an actor's neighbouring poses.
            packet['points'][at] = (packet['points'][at] + points[index]) * .5
            continue
        packet['points'].append(points[index]); packet['depth'].append((depth[index] * scale).astype(np.float32))
        packet['image'].append(images[index]); packet['intrinsics'].append(intrinsics[index].astype(np.float32))
        packet['poses'].append(poses[index].astype(np.float32))
    return packet


def source_is_tripod(images):
    """Lock only when stable features span the frame, not just a face/torso."""
    import cv2
    rgb = np.asarray(images)
    gray = [cv2.cvtColor((np.clip(frame, 0, 1)*255).astype(np.uint8), cv2.COLOR_RGB2GRAY) for frame in rgb]
    points = cv2.goodFeaturesToTrack(gray[0], maxCorners=800, qualityLevel=.01, minDistance=6)
    if points is None or len(points) < 30: return False
    stable = np.ones(len(points), bool)
    for index in np.unique(np.linspace(0, len(gray)-1, min(8, len(gray))).round().astype(int))[1:]:
        tracked, status, _ = cv2.calcOpticalFlowPyrLK(gray[0], gray[index], points, None)
        if tracked is None: return False
        stable &= status[:, 0].astype(bool) & (np.linalg.norm(tracked[:, 0]-points[:, 0], axis=1) < 1.25)
    kept = points[stable, 0]
    if len(kept) < 30: return False
    span = np.ptp(kept, axis=0)
    return bool(span[0] > rgb.shape[2]*.55 and span[1] > rgb.shape[1]*.55)


def project(points, pose, intrinsics):
    camera = (points - pose[:3, 3]) @ pose[:3, :3]
    z = camera[:, 2]
    pixels = camera @ intrinsics.T
    pixels = pixels[:, :2] / np.maximum(pixels[:, 2:], 1e-8)
    return pixels, z


def static_support(points, packet, targets):
    tested = np.zeros(len(points), np.int32)
    supported = np.zeros(len(points), np.int32)
    for index in targets:
        depth = packet['depth'][index]
        height, width = depth.shape
        pixels, z = project(points, packet['poses'][index], packet['intrinsics'][index])
        xy = np.rint(np.nan_to_num(pixels, nan=-1, posinf=-1, neginf=-1)).astype(np.int64)
        inside = (xy[:, 0] >= 0) & (xy[:, 0] < width) & (xy[:, 1] >= 0) & (xy[:, 1] < height) & (z > 1e-5)
        ids = np.flatnonzero(inside)
        observed = depth[xy[ids, 1], xy[ids, 0]]
        tolerance = .05 * np.maximum(observed, z[ids])
        # A closer actor occluding a wall is not evidence that the wall moved.
        visible = np.isfinite(observed) & (observed > 0) & (observed >= z[ids] - tolerance)
        tested[ids[visible]] += 1
        agrees = visible & (np.abs(observed - z[ids]) <= tolerance)
        supported[ids[agrees]] += 1
    return (tested >= min(3, len(targets))) & (supported >= tested * .9)


def grid_mesh(points, depth, image, keep, return_indices=False):
    height, width = depth.shape
    valid = keep & np.isfinite(points).all(-1) & np.isfinite(depth) & (depth > 0)
    ids = np.arange(height * width).reshape(height, width)
    faces = np.concatenate([np.stack([ids[:-1, :-1], ids[:-1, 1:], ids[1:, :-1]], -1).reshape(-1, 3),
                            np.stack([ids[1:, :-1], ids[:-1, 1:], ids[1:, 1:]], -1).reshape(-1, 3)])
    z = depth.reshape(-1)[faces]
    good = valid.reshape(-1)[faces].all(1) & (z.max(1) <= z.min(1) * 1.08)
    faces = faces[good]
    used = np.unique(faces)
    remap = np.full(height * width, -1, np.int64); remap[used] = np.arange(len(used))
    result = points.reshape(-1, 3)[used], remap[faces], image.reshape(-1, 3)[used]
    return (*result, used) if return_indices else result


def srgb_to_linear(colors):
    return np.where(colors <= .04045, colors / 12.92, ((colors + .055) / 1.055) ** 2.4).astype(np.float32)


def fuse_background(backgrounds, side=192):
    """One surface per canonical ray, rather than noisy overlapping meshes.

    Six camera-centred charts retain scenery discovered outside the opening
    frame. Averaging observations on the same ray removes duplicate surfaces
    and z-fighting. This is observed scenery, not invented unseen geometry.
    """
    points = np.concatenate([item[0] for item in backgrounds])
    colors = np.concatenate([item[2] for item in backgrounds])
    axis = np.abs(points).argmax(1)
    sign = points[np.arange(len(points)), axis] >= 0
    faces, vertices, rgb = [], [], []
    offset = 0
    for dimension in range(3):
        for positive in (True, False):
            selected = (axis == dimension) & (sign == positive)
            if not selected.any(): continue
            p, c = points[selected], colors[selected]
            denominator = np.maximum(np.abs(p[:, dimension]), 1e-8)
            u = p[:, (dimension+1) % 3] / denominator
            v = p[:, (dimension+2) % 3] / denominator
            x = np.clip(((u+1)*side/2).astype(int), 0, side-1)
            y = np.clip(((v+1)*side/2).astype(int), 0, side-1)
            ids = y*side+x; counts = np.bincount(ids, minlength=side*side)
            radius = np.bincount(ids, weights=np.linalg.norm(p, axis=1), minlength=side*side)
            radius = (radius / np.maximum(counts, 1)).reshape(side, side)
            image = np.stack([np.bincount(ids, weights=c[:, channel], minlength=side*side)
                              / np.maximum(counts, 1) for channel in range(3)], -1).reshape(side, side, 3)
            keep = counts.reshape(side, side) > 0
            # Only bridge sub-pixel sampling holes, never disoccluded objects.
            from scipy.ndimage import distance_transform_edt
            distance, nearest = distance_transform_edt(~keep, return_indices=True)
            fill = (~keep) & (distance <= 1.5)
            radius[fill] = radius[nearest[0][fill], nearest[1][fill]]
            image[fill] = image[nearest[0][fill], nearest[1][fill]]
            keep |= fill
            yy, xx = np.mgrid[:side, :side]
            rays = np.zeros((side, side, 3), np.float32)
            rays[..., dimension] = 1 if positive else -1
            rays[..., (dimension+1) % 3] = (xx+.5)*2/side-1
            rays[..., (dimension+2) % 3] = (yy+.5)*2/side-1
            rays /= np.linalg.norm(rays, axis=-1, keepdims=True)
            verts, triangles, cols = grid_mesh(rays*radius[..., None], radius, image, keep)
            if not positive: triangles = triangles[:, [0, 2, 1]]
            vertices.append(verts); faces.append(triangles+offset); rgb.append(cols); offset += len(verts)
    if not vertices or not offset:
        raise ValueError('No stable background surface could be fused.')
    return np.concatenate(vertices).astype(np.float32), np.concatenate(faces), np.concatenate(rgb).astype(np.float32)


def scene_tensors(packet, max_side=256):
    """Persistent background mesh plus current-time surfaces, without a human rig."""
    count = len(packet['points'])
    if count < 2:
        raise ValueError('Prepare the shared scene from a video interval.')
    height, width = packet['depth'][0].shape
    stride = max(1, math.ceil(max(height, width) / max_side))
    targets = np.unique(np.linspace(0, count - 1, min(8, count)).round().astype(int))
    backgrounds = []
    for index in targets:
        points, depth, image = (packet[key][index][::stride, ::stride] for key in ('points', 'depth', 'image'))
        keep = static_support(points.reshape(-1, 3), packet, targets).reshape(depth.shape)
        mesh = grid_mesh(points, depth, image, keep)
        if len(mesh[0]): backgrounds.append(mesh)
    if not backgrounds:
        raise ValueError('No consistent scenery could be registered. Use a shorter continuous shot with visible background.')
    points, faces, colors = fuse_background(backgrounds)
    items = []
    for index in range(count):
        current, depth, image = (packet[key][index][::stride, ::stride] for key in ('points', 'depth', 'image'))
        static = static_support(current.reshape(-1, 3), packet, targets).reshape(depth.shape)
        fg_points, fg_faces, fg_colors, indices = grid_mesh(current, depth, image, ~static, True)
        # Real source pixels texture the visible surface. Averaged vertex
        # colours alone blurred faces and lettering even at the source view.
        pixels, z = project(points, packet['poses'][index], packet['intrinsics'][index])
        xy = np.rint(np.nan_to_num(pixels)).astype(np.int64)
        valid = (xy[:, 0]>=0)&(xy[:, 0]<width)&(xy[:, 1]>=0)&(xy[:, 1]<height)&(z>1e-5)
        ids = np.flatnonzero(valid)
        observed = packet['depth'][index][xy[ids, 1], xy[ids, 0]]
        valid[ids] &= np.isfinite(observed)&(np.abs(observed-z[ids]) <= .05*np.maximum(observed,z[ids]))
        photographed = valid[faces].all(1)
        count_bg = len(points)
        combined_points = np.concatenate([points, points, fg_points]) * np.array([1, -1, -1], np.float32)
        combined_faces = np.concatenate([faces[photographed], faces[~photographed]+count_bg,
                                          fg_faces+2*count_bg])[:, [0, 2, 1]]
        # The extra white strip lets the unseen background use its captured
        # colour without interpolating UVs across unrelated atlas regions.
        texture = np.ones((height,width+2,3),np.float32)
        texture[:,:width] = packet['image'][index]
        photo_uv = np.stack([(pixels[:,0]+.5)/(width+2),(pixels[:,1]+.5)/height],1)
        photo_uv = np.clip(np.nan_to_num(photo_uv),0,1)
        fallback_uv = np.repeat(np.array([[(width+1)/(width+2),.5]]),count_bg,0)
        yy,xx = np.divmod(indices,depth.shape[1])
        fg_uv = np.stack([(xx*stride+.5)/(width+2),(yy*stride+.5)/height],1)
        uv = np.concatenate([photo_uv,fallback_uv,fg_uv]).astype(np.float32)
        # Native glTF vertex colours are linear; image textures are sRGB.
        rgb = np.concatenate([np.ones_like(colors),srgb_to_linear(colors),np.ones_like(fg_colors)])
        items.append((combined_points,combined_faces,rgb,uv,texture))
    nv, nf = max(len(item[0]) for item in items), max(len(item[1]) for item in items)
    result = {'vertices': torch.zeros((count, nv, 3)), 'faces': torch.zeros((count, nf, 3), dtype=torch.int64),
              'vertex_colors': torch.zeros((count, nv, 3)), 'vertex_counts': torch.zeros(count, dtype=torch.int64),
              'face_counts': torch.zeros(count, dtype=torch.int64), 'uvs':torch.zeros((count,nv,2)),
              'texture':torch.from_numpy(np.stack([item[4] for item in items]))}
    for index, (vertices, triangles, rgb, uv, _texture) in enumerate(items):
        result['vertices'][index, :len(vertices)] = torch.from_numpy(vertices)
        result['faces'][index, :len(triangles)] = torch.from_numpy(triangles)
        result['vertex_colors'][index, :len(rgb)] = torch.from_numpy(rgb)
        result['uvs'][index, :len(uv)] = torch.from_numpy(uv)
        result['vertex_counts'][index], result['face_counts'][index] = len(vertices), len(triangles)
    return result, {'background_vertices': 2*len(points), 'background_surface_vertices':len(points), 'frames': count,
                    'reference_hfov': math.degrees(2 * math.atan(width / (2 * packet['intrinsics'][0][0, 0]))),
                    'alignment_errors': packet['alignment_errors']}


class ZuraCameraAlignViews:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'geometry': ('DA3_GEOMETRY',), 'start_frame': ('INT', {'default': 0, 'min': 0})},
                'optional': {'previous': ('ZURA_CAMERA_CAPTURE',), 'lock_camera': ('BOOLEAN', {'default': False})}}
    RETURN_TYPES = ('ZURA_CAMERA_CAPTURE',)
    FUNCTION = 'align'
    CATEGORY = 'Zura/Camera'

    def align(self, geometry, start_frame, previous=None, lock_camera=False):
        return (append_views(geometry, start_frame, previous, lock_camera),)


class ZuraCameraPrepareViews:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'image': ('IMAGE',), 'resolution': ('INT', {'default': 504, 'min': 140, 'max': 1008, 'step': 14})}}
    RETURN_TYPES = ('IMAGE', 'BOOLEAN')
    FUNCTION = 'prepare'
    CATEGORY = 'Zura/Camera'

    def prepare(self, image, resolution):
        from comfy.ldm.depth_anything_3.preprocess import compute_target_size
        import torch.nn.functional as functional
        height, width = compute_target_size(image.shape[1], image.shape[2], resolution, 'upper_bound_resize')
        # Enter DA3 at its actual patch raster, so returned pixel intrinsics and
        # depth agree. No ImageNet normalization here: the native node owns it.
        result = functional.interpolate(image.cpu().movedim(-1, 1).float(), size=(height, width),
                                        mode='bicubic', align_corners=False, antialias=True)
        images = result.movedim(1, -1).clamp(0, 1).contiguous()
        return images, source_is_tripod(images.numpy())


class ZuraCameraBuildScene:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'capture': ('ZURA_CAMERA_CAPTURE',), 'cache_key': ('STRING',), 'state_json': ('STRING',)}}
    RETURN_TYPES = ('MESH', 'STRING')
    FUNCTION = 'build'
    CATEGORY = 'Zura/Camera'

    def build(self, capture, cache_key, state_json):
        from comfy_api.latest import Types
        from .panorama_camera import cache_path
        import uuid
        tensors, report = scene_tensors(capture)
        state = json.loads(state_json); state['camera']['fov'] = {'value': report['reference_hfov'], 'keyframes': []}
        state_json = json.dumps(state)
        path = cache_path(cache_key); temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            torch.save({'scene': tensors, 'report': report, 'state_json': state_json}, temporary)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return {'ui': {'zura_camera_state': [state_json], 'zura_scene_report': [report]},
                'result': (Types.MESH(**tensors, unlit=True), state_json)}


class ZuraCameraLoadScene:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'cache_key': ('STRING',)}}
    RETURN_TYPES = ('MESH',)
    FUNCTION = 'load'
    CATEGORY = 'Zura/Camera'

    @classmethod
    def IS_CHANGED(cls, cache_key):
        from .panorama_camera import cache_path
        path = cache_path(cache_key)
        return path.stat().st_mtime_ns if path.exists() else float('nan')

    def load(self, cache_key):
        from comfy_api.latest import Types
        from .panorama_camera import cache_path
        path = cache_path(cache_key)
        if not path.is_file(): raise ValueError('Prepare the shared scene first.')
        return (Types.MESH(**torch.load(path, map_location='cpu', weights_only=True)['scene'], unlit=True),)


class ZuraCameraPadFrames:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'image': ('IMAGE',), 'frames': ('INT', {'default': 17, 'min': 1, 'max': 1000})}}
    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'pad'
    CATEGORY = 'Zura/Camera'

    def pad(self, image, frames):
        if image.ndim != 4 or len(image) < 1:
            raise ValueError('The selected video contains no readable frames.')
        if len(image) >= frames:
            return (image[:frames],)
        return (torch.cat([image, image[-1:].expand(frames-len(image), -1, -1, -1)]),)
