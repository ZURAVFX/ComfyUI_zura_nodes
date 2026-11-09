# Relight models

Choose **Video > Relight**, then choose **Wan 2.1**, **LTX 2.5** or **MiniMax H3** in the model selector.

Wan keeps its existing reviewed lighting-frame and chained-video workflow. LTX and H3 use edited lighting frames on the visual timeline. Add a frame, edit it with a local or browser-sign-in image model, or import an image edited elsewhere. The image-stage prompt is shared with the video stage.

LTX uses one selected lighting image as a visual reference for the whole clip. H3 accepts several timed edited frames. Switching models keeps all the lighting frames; the selected LTX reference does not discard H3's other frames. Relight's draft is saved separately from the ordinary edited-frame workspace.

Changing from Wan carries its current source, selected interval, lighting prompt and reviewed image into the timeline. A smaller working lighting image is resized to the original plate dimensions without cropping before import. Returning to Wan restores the source and selected lighting frame. Source video size, frame rate and selected frame count are restored by the existing native delivery nodes for LTX and H3. Source audio is retained. Processing scale can reduce model memory without changing the delivered raster.

Missing files use the existing model installer and browser-based gated access. The LTX/H3 path currently supports SDR sources. Relighting can still alter surrounding details; compare a generated shot before delivery.

Controller and graph checks cover the model choices, independent drafts, source/trim/prompt/frame preservation, exact frame-rate contract, image return and output folder. These checks reuse the already-tested native edit-propagation renderers; this integration has not added a new GPU quality comparison.
