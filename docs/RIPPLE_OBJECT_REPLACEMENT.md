# Ripple object replacement

Choose **Video > Object replacement · Ripple** in Zura Studio.

1. Import an SDR clip and trim it. The first selected source frame is the replacement guide.
2. Select or paint over the object, including room for its replacement. This mask guides the image edit; it does not track through the video.
3. Add an object reference and describe the replacement, or choose **Use a finished first frame** to import an edited full-size frame.
4. Compare the replacement with the original and click **Use this first frame**.
5. Generate the replacement video. The selected source frame rate and original audio are retained.

Changing the trim requires reviewing the new first frame. Later-frame injection and HDR are not supported in this mode. Use **Inpaint · preview** for the separate any-frame reference workflow. Ripple propagates the edited image without a video mask, so nearby details can also change.

Open **Models** in the workspace to check the complete LTX component package before downloading. The Ripple v11 adapter is about 654 MB; required LTX transformer, text encoder and VAEs are listed separately with their installed state and download sizes. Selecting a package does not start a download.

The adapter comes from [WepeNerd/LTX-Ripple](https://huggingface.co/WepeNerd/LTX-Ripple). Model weights are downloaded separately, rather than bundled with Zura Nodes.
