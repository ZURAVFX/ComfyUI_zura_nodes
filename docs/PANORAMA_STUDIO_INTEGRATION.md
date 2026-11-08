# Panorama camera integration

Included in Zura Studio 1.3.56, 8 November 2026.

## Artist flow

Choose **Change camera angle** in the shared video workflow selector. Import a video with its original audio, trim up to five seconds and choose an output size. Prepare geometry once, then open the native Panorama 3D editor. Apply the camera to create a full-motion warped guide, review it, and render with H3 CrossView. Cancel or closing the camera editor leaves the shot unchanged.

A finished look image is optional. **Create look image** sends the warped opening and original identity frame to the existing image workspace, where local editors and browser sign-in editors remain available. Generating the image is an explicit action. Use the selected image to return to the camera shot. The full-video warp remains the motion guide.

Geometry is cached in `output/genj/panorama/geometry`. Camera changes reuse that geometry; changing the source interval or output raster invalidates it. Graph view exports native nodes without replacing the artist graph while the camera popout is open.

## Geometry options

**Moving subjects · per frame** remains the default. MoGe reconstructs each selected source frame independently, preserving changing body shapes and occlusions. Independent depth estimates can introduce temporal flicker.

**Still scene · MoGe** reconstructs only the first frame of the selected interval and keeps that depth, intrinsics and mesh fixed. The source image is held still across the camera timeline. A separate source-video pane follows the camera playhead and can be played independently. H3 still receives the original moving video performance and audio. Camera keyframes work in the same editor. Switching geometry options invalidates the previous prepared geometry and camera preview.

Locked geometry is intended for static scenes and small source-camera moves. Motion is reconstructed by H3 from the original performance reference; the 3D planning scene itself is a still. Large camera moves can expose missing surfaces or disocclusions. It removes repeated geometry estimation, but does not guarantee a flicker-free final render. It is an alternative guide, not a temporally reconstructed 3D video or Gaussian splat.

The locked geometry option is installed locally. CPU tests cover the selected first frame, repeated still texture, shared tensor storage, cache round trip and unchanged H3 performance/audio paths. A rendered comparison against per-frame geometry remains required before judging the new option's quality.

## Approved recipe retained

The latest supplied GPT-look 1080p, two-second result supersedes the older pending wording in the handover. Native Panorama 2.0.2 supplies the editor and warp; MoGe 3 supplies per-frame geometry. The H3 path retains INT8 Ref2VA, DMD turbo at 1, CrossView Warp at 0.8, Kitchen attention, res_multistep/simple at eight steps, original reference audio and a full-video guide. The look image is a soft guide, not a hard first-frame lock.

H3 receives a 32-pixel-aligned raster and an end-frame hold to its supported frame count. The result is trimmed to the requested frame count and cropped to the chosen output raster. The approved 1920 x 1080 output uses 1920 x 1088 internally.

## Validation and remaining checks

- Twelve native Python camera tests passed, covering guide ancestry, exact frame count, padding, audio paths, soft look guidance, locked geometry and camera/cache state.
- Native handoff and editor DOM tests passed, covering Apply, Cancel and closing the popout; the artist graph is isolated.
- Shared workspace and navigation tests passed, covering the persistent workflow selector and first camera action.
- Isolated headless Playwright checks exercised 20 camera states at 1280 x 720, 1440 x 900, 1920 x 1080 and 768 x 1024. The preview stayed at least 220 px tall, all controls remained visible, and there were no JavaScript errors or horizontal overflow.
- An isolated CPU-only ComfyUI instance loaded the cache nodes and routes, accepted a Studio video upload and built a 24-frame geometry graph without queuing inference.
- Thirty native node schemas were checked against the running installation. Required models exist in the normal installation; the isolated CPU probe does not inherit every external model path.
- An interactive check of the native camera popout and a GPU-rendered comparison of locked versus per-frame geometry remain outstanding. The supplied approved result is quality evidence for the existing recipe, not a fresh end-to-end Studio render.

Source aspect ratio, megapixel scaling and custom dimensions now use the shared resolution pattern, with an 8.39 MP software budget including H3 padding. The supplied approved recipe is 1080p; larger canvases passed graph/padding tests but do not yet have new GPU quality or memory qualification. Silent sources and clips longer than five seconds remain outside this preview. Private handover footage and generated media are not included in the package.
