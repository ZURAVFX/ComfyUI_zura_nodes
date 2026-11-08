# Painted image edits

In **Image → Edit image**, add the main image, choose **Paint area to edit** beside **Main image** and **References**, and paint the part to change. The same control is available when editing a Ripple keyframe. Use the usual prompt and image model, including browser sign-in models. Extra reference images remain separate guides, with their count shown on the References button.

The model receives a crop around the selection. **Blend → Surrounding context** controls how much of the surrounding scene it sees; **Edge softness** blends inward from the painted boundary. The saved result retains the original full-frame dimensions and original pixels outside the selection. **Whole image** returns to ordinary editing.

**Auto** processes small crops at approximately 1 MP and keeps larger crops at their native size, within the model's size limits. A chosen processing size applies to the crop rather than the full frame. The final image still keeps the source dimensions. Completed edits and images selected from History open in the result viewer automatically; the painted selection remains available for another edit.

Image 1 is the source crop; Image 2 and later images are guides. For a replacement, describe what to take from the guide and what to retain from the source, such as the pose, perspective and lighting. Studio sends your prompt unchanged. A painted selection limits the returned composite; it cannot guarantee that the model follows the replacement instruction inside it.

Selections belong to the main image. Changing the model keeps the selection; replacing or removing the main image clears it. Temporary Ripple and frame-extension image edits do not inherit another image's mask.

This optional feature requires [Smart Image Crop and Stitch](https://github.com/HallettVisual/ComfyUI-Smart-Image-Crop-and-Stitch). Studio supports both its older schema and the newer context-padding and feather controls. Models setup reports missing nodes when a painted edit is enabled. Whole-image editing does not require this extension.

The crop and stitch use the installed extension's native nodes. Zura's small CPU adapters validate the source-bound mask and returned crop, and preserve the original source-space selection. A result with a substantially different crop aspect ratio is rejected rather than silently stretched into the wrong region.
