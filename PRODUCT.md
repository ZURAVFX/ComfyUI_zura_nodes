# Zura Studio

<!-- impeccable:product-schema 1 -->

## Platform

Web interface inside ComfyUI, including ComfyUI Desktop. Desktop editing and readable mobile previews are required.

## Stack

Existing vanilla JavaScript and CSS ComfyUI extension, with a Python local orchestration backend. Native editable ComfyUI graphs remain available.

## Users and purpose

Artists transform a reference video through motion transfer, masked swaps of people or objects, or grey viewport renders into final scenes. The interface should be simple enough to use without manipulating node graphs, while preserving graph access for experienced users.

## Confirmed workflows

Users upload a source video and either a finished starting frame or one or more appearance references used to construct a starting look. Text prompts, source previews, selection review, original audio/performance, replacement audio and local voice creation are part of the existing workflow. Uploaded media and private voice examples stay out of public source releases.

## Constraints and evidence

H3 is the recommended viewport route, currently supporting approximately 0.21 to five seconds. Wan remains available for its approved human-performance routes, but is withdrawn from viewport rendering. LTX viewport quality is experimental. Resolution and length must reflect model capabilities rather than promise unsupported renders. Seedance uses paid credits; local UI checks must not queue it.

Native sampling progress may expose steps. Loading and other stages without measurable totals must show a named loading state; remaining-time estimates are measured and scoped to the active stage. Subject detection is local CPU advice, with explicit People and Objects overrides.

## Approved design direction

The user supplied and approved a dark navy/purple Zura editor composition: source and starting-look controls on the left, a large video preview and takes in the centre, shot settings and actions on the right, with a clear Source / Look / Review / Generate sequence. Adapt it to real app capabilities and smaller screens. Do not add mock accounts, decorative window controls or unsupported output options.
