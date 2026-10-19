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

The current direction is the user's Artify reference: a quiet charcoal canvas,
compact tools and a persistent prompt plus primary action. Zura retains its
actual logo, with Artify-inspired lime actions and a saved dark/light theme. A simple Home screen offers Image and Video.
Image contains three locally tested native recipes for 16 GB hardware. Video
preserves approved shot routes with source/look controls and a collapsible
settings section. Do not introduce decorative account controls, mock galleries,
paid generation, or unsupported output options. The previous navy three-column
layout is superseded by this canvas-first composition.
