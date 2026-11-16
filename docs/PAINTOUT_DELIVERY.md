# Paintout compositing files

Finished Paintout results expose a compact save row alongside Alpha's save row.
It offers the actual available ProRes master, EXR/frame archive or single image,
plus the repair mask MOV and lossless PNG16 mask-frame archive.

The repair mask is full source size. White selects the generated repair, black
retains the original plate, and intermediate values are the final blend weight.
It includes repair expansion, feathering and protected regions. Subtitle repair
exports the processed rectangle's edge blend. Source frame numbering and exact
rational frame rate are recorded in `mask_info.json` inside the PNG archive.

EXR archives contain the rendered files without colour conversion or re-encoding.
The repair matte remains available when the RGB subsequently goes through HDR
conversion. Result history retains explicit export references; older results
show their existing assets without invented companion paths.

Alpha offers transparent MOV, matte MOV and its existing PNG16 matte frames.
Both workflows use lightweight playback previews while downloads retain the
compositing masters. Mask files stay separate from the beauty/master selected
for AE return.
