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

H3 is the recommended viewport route, currently supporting approximately 0.21 to five seconds. Wan remains available for its approved human-performance routes, but is withdrawn from viewport rendering. LTX viewport is excluded after its rejected quality test. Resolution and length must reflect model capabilities rather than promise unsupported renders. Seedance uses paid credits; local UI checks must not queue it.

Native sampling progress may expose steps. Loading and other stages without measurable totals must show a named loading state; remaining-time estimates are measured and scoped to the active stage. Subject detection is local CPU advice, with explicit People and Objects overrides.

## Colour and delivery requirements, 16 November 2026

Studio has no user-facing colour-transform menu. Do not reintroduce the retired
preview dropdown or a second Source options panel. Source interpretation is
automatic; advanced file settings live in Settings.

Keep captured working RGB and its original EXR data separate from the SDR copy
used by image models. The Preserve RGB source preview follows the numeric AE
appearance without an added gamma adjustment. Native HDR-capable LTX routes use
the retained original; other HDR outputs use their explicit reconstruction step.

Save actual PNG files for 8/16-bit stills, EXR for float stills and sequences,
and ProRes 4444 MOV for video masters and AE delivery. Browser MP4 files are
viewing proxies. Keep both the final repair and its processing mask available.

AE timing and model timing are distinct. Reinterpret the same ordered frames at
a supported model rate, then restore the exact original rational rate and audio
timing on delivery. Remove only model padding. A different source fps is not,
by itself, a reason to reject an otherwise supported shot.

## AE session source requirement, 14 November 2026

The received AE shot belongs to the session and remains attached across Studio
mode changes. Every mode with a source canvas or source attachment must show
that same retained shot. Load AE source must bind the existing session source
to the active mode without requiring a resend from AE.

Source visibility and processing eligibility are separate. A preview-only AE
source remains visible when a mode cannot process its colour profile or sample
type. It must not be represented by an invented file, silently converted, or
substituted by an independently selected old source during generation. Preserve
the actual source identity, range and selected frame across mode changes.

## Approved design direction

The current direction is the user's Artify reference: a quiet charcoal canvas,
compact tools and a persistent prompt plus primary action. Zura retains its
actual logo, with Artify-inspired lime actions and a saved dark/light theme. The app opens directly in Video, with Image available in the shared header. Model downloads stay available beside the workspace controls.
Image contains three locally tested native recipes for 16 GB hardware. Video
preserves approved shot routes with source/look controls and a collapsible
settings section. Do not introduce decorative account controls, mock galleries,
paid generation, or unsupported output options. The previous navy three-column
layout is superseded by this canvas-first composition.

## UI consistency requirements, 16 November 2026

Preserve the refined charcoal canvas, paint toolbar and compact bottom composer.
Use the shared brush-size control and palette in Image Edit, Add/Replace and
Paint VFX. Sizes use source pixels, precise numeric entry and the same keyboard
increments. Moving an editor must not duplicate its controls or listeners.

Use one progress owner for the active workspace. Repair stages navigate through
the top steps; navigation never submits generation. Prompt text uses Enter for
a new line and Ctrl/Cmd+Enter for the enabled primary action.

Character replacement proceeds through source, mask review, reference-frame
review, video and result. Mask preparation requires no character reference.
Generation requires an explicit action at each checkpoint. Keep previous takes
available after a failed submission, and never send a hidden old take to AE.
