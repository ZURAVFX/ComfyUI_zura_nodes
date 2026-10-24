# Longer video status

Existing Wan character replacement uses bounded windows and carried context.
Its previously reported chunk blending remains a known quality limitation.

The new first/last frame and H3 reference-video workspaces currently generate
one native window. Their frame limits are model limits, not a guarantee that
the maximum fits every GPU. They do not silently repeat independent clips.

Before enabling longer generation for these workspaces:

1. Add a coordinator which carries native H3 continuation state or a rolling
   LTX latent tail between bounded windows.
2. Trim overlap as each window completes and save only its owned frames.
3. Concatenate file-backed encoded videos, then restore one continuous audio
   track. Avoid holding the complete decoded clip in system memory.
4. Reset carried state at camera cuts and verify timestamps, frame counts,
   audio alignment and seam quality on a real long clip.

The installed native `ConcatenateVideo` and `Video Slice` nodes provide the
file-backed joining and trimming primitives. H3 continuation state nodes and
LTX extension sampling exist, but the new workspace coordinator and quality
qualification are still pending. Long generation stays unavailable there
until those checks pass.
