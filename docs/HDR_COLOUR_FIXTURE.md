# HDR ingest colour regression

`tests/test_hdr_colour_fixture.py` creates neutral Rec.2020 swatches in limited-range 10-bit YCbCr, encodes them losslessly as PQ and HLG HEVC, checks the resulting colour metadata, and loads them through Studio's native HDR input path. The decoded scene-linear values are compared with independently calculated BT.2100 transfer functions, using the pipeline's 203-nit reference white and 1,000-nit HLG display assumption. Highlights above scene-linear 1 must survive. Two frames must also decode identically.

The HLG fixture is also staged and exported through the real streaming HLG delivery path, then decoded again. The test checks the delivered frame count, 10-bit pixel format and Rec.2020 HLG metadata, along with the swatches and highlights. The exported HEVC is lossy, so the round-trip comparison allows an 8% or 0.035 scene-linear absolute tolerance, whichever is larger.

Run with ComfyUI's Python, its root on `PYTHONPATH`, and `ffmpeg` and `ffprobe` on `PATH`:

```text
python -m unittest discover -s tests -p test_hdr_colour_fixture.py -v
```

The test skips if FFmpeg, ffprobe or the libx265 encoder is unavailable. It exercises the real encoded input and streaming HLG delivery, without a GPU. It does not establish colour fidelity through a generative model, validate the separate graph-based delivery path, or qualify colour accuracy for coloured footage. Neutral swatches test transfer and range handling only.
