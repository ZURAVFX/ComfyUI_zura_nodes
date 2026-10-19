# Change camera angle

Choose **Change camera angle** in Zura Studio to reframe a short performance with MiniMax H3 CrossView.

1. Upload your source video and choose the clip interval. Start with two seconds. This route currently requires the original audio track.
2. Choose a camera angle and optionally describe the framing. Identity and room references are optional. You can also choose **Use camera still** to upload an image already composed from the desired viewpoint.
3. Select **Create camera still**. Review the angle, identity, clothing and framing in the large preview. **Regenerate camera still** makes another version. Changing the camera direction requires an updated still before video generation.
4. Select **Use this angle & generate** to approve the still and render the original performance from the new view. Compare the result with the source and download a take.

The camera still and video are separate runs, so regenerating an image never queues a video. The approved still is saved and reused during animation. Graph view opens an editable copy of the current stage, with native processing nodes.

## Tested recipe

The local recipe uses the INT8 Ref2VA H3 model, its matching 8-step Turbo adapter at 1.0, CrossView Warp LoRA at 0.8, video/audio sigma shifts of 12/3, Comfy Kitchen attention and `res_multistep` / simple sampling. `crossview.` precedes the camera direction and reference roles in the video prompt.

The approved camera image is Picture 1, the image guide and the locked first video latent. The source clip supplies performance and original audio separately. No geometry warp, segmentation or edit mask is used. Optional identity and room references keep distinct prompt roles.

The approved test was two seconds at 768 × 448 and 24 fps. The route permits up to five seconds; longer takes and other angles still need review for drift, expression changes and invented hidden details. Timing depends on model residency and system memory; the measured test speed is not a guaranteed render time.

The setup checklist checks the image and video stages independently, including the CrossView adapter. An uploaded camera still bypasses image generation and its model requirements. Private test media and prompts are not included in the release.
