# Studio video delivery

Final SDR videos and the former HLG video deliveries use ProRes 4444 MOV.
SDR/HDR remains the artist-facing output choice. PNG/EXR still delivery is
unchanged. HDR EXR masters retain their existing full working values.

Movie output has no HLG/display/gamut transform. SDR movies retain their
display-referred RGB; HDR movies retain the producer's working encoding
(ACEScct or linear ACEScg). The encoding is carried on the output reference,
in the MOV comment, and in a small metadata sidecar. The MOV is not promised
to look natural in an unmanaged player.

ProRes uses fixed-point, compressed samples. It cannot exactly retain arbitrary
float values, negative RGB or above-one linear values. The EXR is authoritative
for those values. No range mapping is invented to fit them into the movie.
Alpha is retained when available to the movie writer.

Native frame/reference/Director/Paint VFX movie savers write directly from VIDEO
components. A separate returned MP4 reference is for browser playback only;
downloads and AE descriptors retain the MOV. Existing ProRes movies with the
correct AE clock/raster are reused. Older MP4 results can be converted once to
an AE-timed ProRes master, including source audio.

Legacy `hlg_video`, `hlg_and_exr` and Paintout format values remain accepted
internally so saved workflows stay readable. They now select ProRes delivery.
Old published files are not rewritten, and genuine HLG/PQ source decoding stays
available. New node registrations require a ComfyUI backend restart.
