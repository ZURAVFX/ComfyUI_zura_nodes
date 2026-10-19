---
colors:
  background: "#080c13"
  surface: "#101620"
  border: "#303b50"
  primary: "#7846f7"
  foreground: "#f0f1f3"
  muted: "#b4bfd2"
  primary-hover: "#8150fa"
  primary-soft: "#d0bfff"
  primary-surface: "#241b48"
  canvas: "#060a11"
  warning-surface: "#211c37"
  warning-border: "#55467a"
  warning-text: "#d7cded"
  shell-light: "#26334d"
  panel-light: "#151d2b"
  input: "#131c29"
  input-light: "#172130"
  control-border: "#62728c"
  focus: "#b8a4ff"
  selected-border: "#a28aff"
  step-light: "#ac91ff"
  step-violet: "#865cff"
  step-ink: "#100b24"
  action: "#743df7"
  action-end: "#6734e9"
  action-hover-end: "#7748f5"
  ready: "#b9ed70"
---

# Zura Studio design system

## Overview

Zura Studio is a local video editing workspace. The user-approved direction is a dark navy interface with violet actions, a large real-media preview and compact editing controls. The surface operates as an editor, with product clarity ahead of decoration.

## Colors

The CSS variables on `#genj-studio` define the palette above. Violet identifies the current stage, selection, focus and primary action. Text and controls use navy surfaces with a restrained overhead light across the shell. Elevated panels and inputs use tonal navy shading; active stages and selected controls use brighter violet. The primary button owns the strongest violet. The supplied Zura logo is used unchanged, displayed in silver on the dark header using CSS inversion and screen blending. Readiness retains a green dot beside its text label. Warnings explain the recovery beside the action they affect.

## Typography

Segoe UI with system sans-serif fallbacks. Base text is 14 px. Compact labels are 12–13 px; panel headings are 18 px. Mobile inputs use 16 px text and a 44 px minimum height.

## Layout

Desktop uses three columns: source, references and prompt on the left; the actual source/review/result player and real takes in the centre; model, output, trimming, audio and generation on the right. Source, Look, Review and Generate navigation reflects real state and moves focus to relevant controls. Graph view remains in the header.

Below 1241 px the controls and settings form the left column beside the preview. At 900 px and below the panels stack as source/look, preview, then settings. Mobile progress sits below the video rather than covering it.

## Components

Uploads show the actual thumbnail and filename. Finished-frame and reference-built looks remain separate choices. Prompt stays visible. Optional setup, voice generation and technical controls use disclosure panels. The primary action lives with shot settings.

The progress bar represents the current stage only. Unknown progress is indeterminate. Remaining time is labelled as an estimate and appears only after measured timing is available. Cancel run remains beside live progress. An oversized source selection enables Choose clip length, which suggests a valid custom interval and focuses the seconds field without queuing generation.

Progress keeps the artist's operation in the heading and the current native processing step beneath it. Model handoffs, queue waits and model loading clear previous sampling percentages, step counts and time estimates immediately. Measured remaining time describes the active step, rather than promising a finish time for the entire shot.

Change camera angle uses the approved H3 CrossView recipe with its own angle preset and direction prompt. Up to five optional references have Person or Room roles, or the artist can upload a finished camera still. One primary action creates the still; after review it becomes Use this angle & generate. Regeneration is a secondary action beside camera direction. Changing that direction requires a new still before video controls appear. The route hides masks, duplicate prompts, replacement audio and fixed sampler settings. It requires source audio and describes the approved two-second test separately from the supported five-second limit. Source / Camera still / Review & render / Result navigation reflects this flow.

State transitions use short ease-out changes. Indeterminate progress conveys ongoing work. Reduced-motion preferences disable animation and transitions.

## Do's and Don'ts

Keep native labelled inputs, keyboard focus outlines, current-step ARIA and progressbar semantics. Do not invent results, source imagery, account avatars or unsupported controls. Browser restrictions currently prevent visual verification; source and behavioural checks do not imply a completed browser review.

Clip length uses visible Use source / Custom buttons with selected and focus states, instead of a native menu. Remaining native option popups have explicit dark surface and readable text colours.


## Character creation flow

Source contains the video, clip interval and appearance references. The optional first-frame prompt belongs beside those references. One main action creates the starting frame, including source preparation, without queuing animation. The centre previews the resulting frame and offers Selection / Guidance / Original tabs for inspection. Video resolution, sampling and audio controls appear after the frame exists. Regenerate is a secondary revision action available only for an existing frame. The main action then becomes Generate video. Direct-portrait and direct-viewport workflows retain their explicit shortcuts.
