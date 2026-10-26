# Start here: v1.0.0-rc.1

Use a copy of a short, continuous shot. Start with a visible object against a recoverable background. The bedroom overlap test is a stress test and remains unsuitable as the final demonstration.

## First test

1. If ComfyUI shows its first-run template chooser, close it to reach Paintout. Choose Targeted repair or Full-scene clean plate, then add footage. Check its original dimensions, duration and frame rate. For an image sequence, set its intended frame rate before working.
2. In Mask, describe the subject or use Select subject / Exclude area points. Preview the mask, then track it. If several subjects match, choose the intended subject from the previews; cancellation keeps the saved mask. Alternatively use Import mask video: white removes, black keeps; match the original plate dimensions, frame rate and full length. Drag the timeline In and Out handles to choose the source range; focused handles also accept arrow keys for one-frame adjustments. Scrub the entire range, especially entry, exit and overlap frames. Trimming never renumbers or deletes your guides.
3. Use Add missed coverage for gaps. Use Protect this region to preserve a foreground subject. Scrub to any frame and use Paint mask or Erase mask to fix it. Corrections save automatically to that frame. Adjust Expand mask while watching the hard red boundary; Red overlay only changes display opacity. Track a correction through a section explicitly if needed. Mark genuinely absent sections explicitly. Use Review next change for amber warnings; confirm it seeks only within the trim and does not change masks. Inspect the result yourself: area checks cannot reliably identify occlusion.
4. Scrub to the desired frame and click Add clean frame (or press K while the timeline is focused). Paint the unwanted area, including shadows if needed, and expand this guide’s mask independently of the video mask. Run FLUX, compare with the original and accept only a fully clean result. Press X to discard an unaccepted result; the mask stays and the next attempt uses a new seed. X while typing in an input has no discard action. Add two or three informative guides where the background or occlusion changes.
5. Test the external-edit route: download one original, edit it and import it onto the same frame card. The image must retain source dimensions and have normal orientation. Drag-and-drop imports are also supported. Change one area inside the repair and another outside it: the latter must appear in red during review. Test Keep current repair area and confirm the outside change is excluded, then reimport and test Include highlighted edits. Only this clean guide should expand; the shot removal mask must remain unchanged. Press X on an imported candidate and check that the earlier accepted image, guide mask and seed remain. Once a card has two accepted images, use Saved version to switch between them. Confirm the viewer changes, then reload the browser and check that the same card, playhead and chosen image return. A pending FLUX candidate must be accepted or discarded before switching saved versions.
6. In Render, the mask from step 1 is used automatically. Incomplete mask coverage directs you back to Mask. Check range, prompt and export format. Processing stretches to the nearest larger 64-pixel grid. Delivery retains the original dimensions, frame rate and selected number of frames. Choose EXR + SDR video for a reviewable master and preview.
7. Play the result, inspect edges frame by frame and compare the scene outside the repair. Report remnants, jitter, texture changes and unwanted edits separately from UI faults.

## Reliability checks

- Reopen the project from Projects, reload the browser and verify guides, frame numbers, mask revision and settings.
- Switch Mask / Clean frames / Render, then Source / Result. No stale overlay should remain on the result.
- Cancel a queued or running tool job. Only that job should stop; the previous accepted guide must survive.
- Import a wrong-size image. It should be rejected without replacing the accepted guide.
- Try dark/light themes, window resizing, zoom/pan, timeline zoom, arrow keys and K to add a guide.
- Open the editable graph and return to the workspace. Essential controls and native model stages remain editable.
- Check output with your usual VFX tool: width, height, frame rate, frame count, first/last frame and audio synchronisation.

## Feedback format

Copy this for each issue:

```
Build: 1.0.0-rc.1
Shot: name, dimensions, frame rate, selected source range
Stage: Mask / Clean frames / Render / Project / Install
Steps:
Expected:
Actual:
Frame numbers:
Screenshot or short recording:
ComfyUI error if present:
Priority: prevents work / workaround available / polish
```

No lower-resolution processing proxy is substituted automatically. Plates above the current 4096-pixel-per-side limit are rejected. Model memory limits can require a shorter section. Variable-frame-rate or rotated video must be conformed first. AI clean-frame editing is currently SDR; use edited EXR/TIFF guides for HDR. EXR delivery carries RGB, not source alpha, AOVs or all source headers. Video previews may be smaller than the master; judge master dimensions using the main export or EXR sequence. Odd-size video masters use 4:4:4 encoding to preserve dimensions; some players may need an EXR or an even-size viewing proxy.

Do not call this final v1 until your acceptance pass is complete.

## Mask segments and clean-frame expansion

- Scrub to where tracking first loses a visible subject. Choose **Repair tracking from here**, select the subject again, preview the selection and track the segment. Set In/Out and direction explicitly when needed. Earlier frames outside the segment must remain unchanged.
- Choose **Add another mask** for an additional subject or region. Preview and track its independent selection; existing masks should remain. Inspect saved passes under **Tracking segments**. Reappearance after full occlusion may need another seeded segment.
- In **Clean frames**, select an accepted frame and increase **Expand mask**. The red boundary must expand immediately and remain after switching frames. This changes only that guide. A pending generated candidate locks expansion until accepted or discarded with X. Generate again to apply changed bounds to a new result.
