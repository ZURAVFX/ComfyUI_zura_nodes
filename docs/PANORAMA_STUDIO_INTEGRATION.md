# Panorama camera integration

Local development, 31 October 2026. Not a public release.

## Artist flow

Choose **Change camera angle** in the shared video workflow selector. Import a video with its original audio, trim up to five seconds and choose an output size. Prepare geometry once, then open the native Panorama 3D editor. Apply the camera to create a full-motion warped guide, review it, and render with H3 CrossView. Cancel or closing the camera editor leaves the shot unchanged.

A finished look image is optional. **Create look image** sends the warped opening and original identity frame to the existing image workspace, where local editors and browser sign-in editors remain available. Generating the image is an explicit action. Use the selected image to return to the camera shot. The full-video warp remains the motion guide.

Geometry is cached in `output/genj/panorama/geometry`. Camera changes reuse that geometry; changing the source interval or output raster invalidates it. Graph view exports native nodes without replacing the artist graph while the camera popout is open.

## Geometry options

**Moving subjects · per frame** remains the default. MoGe reconstructs each selected source frame independently, preserving changing body shapes and occlusions. Independent depth estimates can introduce temporal flicker.

**Stable scene · locked** reconstructs only the first frame of the selected interval and keeps that depth, intrinsics and mesh fixed. Every selected video frame still supplies its own moving texture, and H3 still receives the original video performance and audio. Camera keyframes work in the same editor. Switching geometry options invalidates the previous prepared geometry and camera preview.

Locked geometry is intended for static scenes and small source-camera moves. Moving people or objects can slide across the fixed surface or expose its old silhouette. It removes repeated geometry estimation, but does not guarantee a flicker-free final render. It is an alternative guide, not a temporally reconstructed 3D video or Gaussian splat.

CPU tests cover the selected first frame, full moving texture batch, shared tensor storage, cache round trip and unchanged H3 performance/audio paths. A rendered comparison against per-frame geometry remains required before judging the new option's quality.

## Approved recipe retained

The latest supplied GPT-look 1080p, two-second result supersedes the older pending wording in the handover. Native Panorama 2.0.2 supplies the editor and warp; MoGe 3 supplies per-frame geometry. The H3 path retains INT8 Ref2VA, DMD turbo at 1, CrossView Warp at 0.8, Kitchen attention, res_multistep/simple at eight steps, original reference audio and a full-video guide. The look image is a soft guide, not a hard first-frame lock.

H3 receives a 32-pixel-aligned raster and an end-frame hold to its supported frame count. The result is trimmed to the requested frame count and cropped to the chosen output raster. The approved 1920 x 1080 output uses 1920 x 1088 internally.

## Validation and remaining checks

- Eight CPU graph tests cover guide ancestry, exact frame count, padding, audio paths, soft look guidance and camera/cache state.
- DOM tests cover native Apply, Cancel and closing the popout; the artist graph is isolated.
- Shared workspace tests cover the persistent workflow selector and first camera action.
- An isolated CPU-only ComfyUI instance loaded the cache nodes and routes, accepted a Studio video upload and built a 24-frame geometry graph without queuing inference.
- Thirty native node schemas were checked against the running installation. Required models exist in the normal installation; the isolated CPU probe does not inherit every external model path.
- No new GPU render or visual native-popout check was performed in this integration session. Browser visual testing remains unavailable. The supplied approved result is quality evidence for the recipe, not a fresh end-to-end Studio render.

Silent sources, longer than five seconds and outputs above 1080p remain outside this preview. Private handover footage and generated media are not included in the package.
