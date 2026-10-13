---
colors:
  background: "#0d1119"
  surface: "#141a25"
  border: "#30394b"
  primary: "#7850ed"
  foreground: "#f0f1f3"
  muted: "#b0bacb"
  primary-hover: "#8964ff"
  primary-soft: "#c6b5ff"
  primary-surface: "#30244f"
  canvas: "#090d14"
  warning-surface: "#211c37"
  warning-border: "#55467a"
  warning-text: "#d7cded"
---

# Zura Studio design system

## Overview

Zura Studio is a local video editing workspace. The user-approved direction is a dark navy interface with violet actions, a large real-media preview and compact editing controls. The surface operates as an editor, with product clarity ahead of decoration.

## Colors

The CSS variables on `#genj-studio` define the palette above. Violet identifies the current stage, selection, focus and primary action. Text and controls use neutral navy surfaces. Warnings explain the recovery beside the action they affect.

## Typography

Segoe UI with system sans-serif fallbacks. Base text is 14 px. Compact labels are 12â€“13 px; panel headings are 18 px. Mobile inputs use 16 px text and a 44 px minimum height.

## Layout

Desktop uses three columns: source, references and prompt on the left; the actual source/review/result player and real takes in the centre; model, output, trimming, audio and generation on the right. Source, Look, Review and Generate navigation reflects real state and moves focus to relevant controls. Graph view remains in the header.

Below 1241 px the controls and settings form the left column beside the preview. At 900 px and below the panels stack as source/look, preview, then settings. Mobile progress sits below the video rather than covering it.

## Components

Uploads show the actual thumbnail and filename. Finished-frame and reference-built looks remain separate choices. Prompt stays visible. Optional setup, voice generation and technical controls use disclosure panels. The primary action lives with shot settings.

The progress bar represents the current stage only. Unknown progress is indeterminate. Remaining time is labelled as an estimate and appears only after measured timing is available. Cancel run remains beside live progress. An oversized source selection enables Choose clip length, which suggests a valid custom interval and focuses the seconds field without queuing generation.

State transitions use short ease-out changes. Indeterminate progress conveys ongoing work. Reduced-motion preferences disable animation and transitions.

## Do's and Don'ts

Keep native labelled inputs, keyboard focus outlines, current-step ARIA and progressbar semantics. Do not invent results, source imagery, account avatars or unsupported controls. Browser restrictions currently prevent visual verification; source and behavioural checks do not imply a completed browser review.
