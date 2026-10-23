---
colors:
  background: "#101013"
  surface: "#19191e"
  composer: "#222228"
  border: "#33333d"
  primary: "#caff00"
  foreground: "#f2f2f0"
  muted: "#a3a3aa"
  selected: "#292a21"
  hover: "#26262b"
  focus: "#d7ff50"
  warning-indicator: "#edb977"
  error: "#e77e70"
  overlay-backdrop: "rgba(0,0,0,.73)"
  floating-shadow: "rgba(0,0,0,.25)"
  light-background: "#f5f5f1"
  light-surface: "#ffffff"
  light-input: "#f0f0eb"
  light-border: "#dcdcd5"
  light-foreground: "#202019"
  light-muted: "#686861"
---

# Zura Studio design system

The prompt composer follows the supplied compact video-generator reference: attachments on the upper left, a single unboxed writing surface, then model, dimensions, clip length, audio and advanced tools in a bottom row. The primary action sits at the right. Use a single workflow selector rather than the cramped multi-line mode grid. Detailed controls open above the composer or in the inspector, preserving the central media canvas.

## Overview

Zura Studio is a local creative workspace for image and video generation. The user-approved direction follows Artify: a quiet charcoal canvas, compact tools, a persistent bottom prompt and a single acid-lime primary action. Dark and light themes share the same layout and save the user's choice.

## Colors

The scoped CSS variables on `#genj-studio` define the palette above. Charcoal distinguishes the canvas, tools and prompt surface. Lime marks the primary action, selected model, current step and focus. The supplied Zura logo remains unchanged. Readiness uses a green status dot with a text label. Warnings explain the recovery beside the action they affect.

## Typography

Segoe UI with system sans-serif fallbacks. Base text is 14 px. Compact labels are 12–13 px; panel headings are 18 px. Mobile inputs use 16 px text and a 44 px minimum height.

## Layout

The app stays within the Comfy window. Video uses a compact inspector beside a large real-media canvas and a prompt composer at the bottom. Only the active inspector and long result lists scroll. Image generation keeps the canvas, optional settings rail, references and prompt together. Home offers clear Image and Video entry points. Graph view remains in the header.

## Components

Uploads show the actual thumbnail and filename. Finished-frame and reference-built looks remain separate choices. Prompt stays visible. Optional setup, voice generation and technical controls use disclosure panels. The primary action lives with shot settings.

The progress bar represents the current stage only. Unknown progress is indeterminate. Remaining time is labelled as an estimate and appears only after measured timing is available. Cancel run remains beside live progress. An oversized source selection enables Choose clip length, which suggests a valid custom interval and focuses the seconds field without queuing generation.

Progress keeps the artist's operation in the heading and the current native processing step beneath it. Model handoffs, queue waits and model loading clear previous sampling percentages, step counts and time estimates immediately. Measured remaining time describes the active step, rather than promising a finish time for the entire shot.

Change camera angle uses the approved H3 CrossView recipe with its own angle preset and direction prompt. Up to five optional references have Person or Room roles, or the artist can upload a finished camera still. One primary action creates the still; after review it becomes Use this angle & generate. Regeneration is a secondary action beside camera direction. Changing that direction requires a new still before video controls appear. The route hides masks, duplicate prompts, replacement audio and fixed sampler settings. It requires source audio and describes the approved two-second test separately from the supported five-second limit. Source / Camera still / Review & render / Result navigation reflects this flow.

State transitions use short ease-out changes. Indeterminate progress conveys ongoing work. Reduced-motion preferences disable animation and transitions.

## Do's and Don'ts

Keep native labelled inputs, keyboard focus outlines, current-step ARIA and progressbar semantics. Do not invent results, source imagery, account avatars or unsupported controls. Source and behavioural checks do not replace a live visual review.

Clip range uses Use source / Trim buttons and a source filmstrip with draggable start/end handles. Precision timing is collapsed beneath it. Dragging seeks the source and commits once on release, with frame-level keyboard adjustments. Remaining native option popups have explicit dark surface and readable text colours.


## Character creation flow

Source contains the video and appearance references. The video canvas and bottom composer remain in view while the selected source or settings panel owns its own scroll. Image and video prompts keep distinct text; camera direction uses the same visible composer even with an uploaded camera still. One main action creates the starting frame, including source preparation, without queuing animation. The centre previews the resulting frame and offers Selection / Guidance / Original tabs for inspection. Camera stills do not require a mask-review record, and stills and videos can be expanded fullscreen. Video resolution, sampling and audio controls appear after the frame exists. Regenerate is a secondary revision action available only for an existing frame. The main action then becomes Generate video. Direct-portrait and direct-viewport workflows retain their explicit shortcuts.

## October 2026 Image / Video overhaul

The Artify reference supplied by the user supersedes the earlier three-column
composition described above. `studio_create.css` is the new shell layer.
Charcoal ground (#101013), slightly lighter tools (#19191e), composer (#222228),
quiet borders (#33333d), acid-lime actions and the unchanged real logo replace
the navy overhead glow. Typography remains the established system sans-serif.

Home offers two clear choices. Image uses one compact model/shape sidebar, a
real-output gallery, and a persistent prompt + Generate image composer. Small
screens hide settings behind a labelled Settings button while keeping the
composer visible. No stock gallery implies generated user results.

Video keeps its proven stage logic and controls but folds model/quality/audio
into Generation settings. The primary action moves to the prompt composer.
Trimming has its own disclosure so the prompt remains visible. Native Graph
view and saved shots remain accessible. The latest implementation and
qualification limits are documented in docs/IMAGE_STUDIO.md.

## Appearance update

The user requested a closer match to Artify: neutral charcoal with acid-lime primary actions replaces the violet accent in Studio. A persistent header toggle offers a warm-white light appearance with dark text. `zura-studio-theme` saves the explicit choice in local browser storage. Image dimensions have labelled width/height fields and a swap action, alongside shape presets.

## Artify canvas refinement, 20 October 2026

The user reconfirmed Artify as the governing reference. Image settings are closed
initially and open through a labelled Settings control; Escape and Done close the
inspector without discarding edits. Desktop uses the available canvas width with
an optional 280px inspector and 24px gutters. Mobile uses a bounded settings sheet.
The prompt and references stay together in a centred, maximum 960px composer.
Headers are compact task names, not promotional copy. The Home choices have no
synthetic illustration. Video retains its existing stage logic with quieter,
narrower setup controls. Dark/light preferences and all generation recipes remain.

This pass has DOM and regression coverage. Live visual sign-off in the installed
Comfy window remains outstanding. It is not published.


## Shared component foundation

The user selected daisyUI and Web Awesome together. daisyUI styles native fields
and actions with zu-prefixed classes scoped to #genj-studio; Web Awesome supplies
contextual tooltips. Both inherit the same saved dark/light Zura palette.
Bundles are local; no CDN, external font or paid component is required. Native
field IDs and events remain intact. Existing text hints remain if tooltips fail.
The video composer has one surface, no duplicate visible field label, and a
horizontal footer linking the prerequisite message to the primary action.
