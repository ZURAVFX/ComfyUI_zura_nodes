"""Private long HDR outpaint coordinator: SDR guide stage only.

The caller owns an exclusive scratch destination, generated anchors, child
artifact verification and cleanup. HDR conversion/export are separate stages.
"""
import asyncio
from pathlib import Path
import uuid

from .hdr_outpaint_long_plan import plan_hdr_windows, long_plan_values, build_long_hdr_sdr_window, build_long_hdr_review_window
from .outpaint_long_runner import run_windows


async def run_long_hdr_review(*, source, selection, review_key, submit, wait,
                              cancel, update, ffmpeg, output, check_asset):
    """Render and assemble a full-range HDR canvas review without sampling."""
    values=long_plan_values(selection)
    expected,parts,subplans=plan_hdr_windows(source,duration=selection['requested_duration'],
                                               **values)
    if selection.get('review_key')!=expected['review_key'] or review_key!=expected['review_key']:
        raise ValueError('The full HDR selection changed. Review it again.')
    destination=Path(output)
    if destination.exists():raise ValueError('The HDR review already exists; choose a new job destination.')
    async def submit_window(kind,asset,subplan,previous):
        graph=await asyncio.to_thread(build_long_hdr_review_window,asset,expected,subplan,
            review_key=review_key,prefix='genj/hdr_outpaint/'+uuid.uuid4().hex,check_asset=check_asset)
        return await submit(subplan,graph)
    return await run_windows(kind='review',source=source,selection=expected,parts=parts,
        subplans=subplans,submit=submit_window,wait=wait,cancel=cancel,update=update,
        ffmpeg=ffmpeg,output=destination,source_audio=None,anchor=False)


async def run_long_hdr_sdr_pass(*, source, selection, review_key, prompt, seed,
                                submit, wait, cancel, update, make_anchor,
                                ffmpeg, output, check_asset):
    values=long_plan_values(selection)
    expected, parts, subplans = plan_hdr_windows(source, duration=selection['requested_duration'],
                                                   **values)
    if selection.get('review_key') != expected['review_key'] or review_key != expected['review_key']:
        raise ValueError('The full HDR selection changed. Review it again.')
    destination = Path(output)
    if destination.exists():
        raise ValueError('The HDR intermediate already exists; choose a new job destination.')

    async def submit_window(kind, asset, subplan, previous):
        anchor = await make_anchor(*previous) if previous is not None else None
        graph = await asyncio.to_thread(build_long_hdr_sdr_window, asset, expected, subplan, review_key=review_key,
            anchor_file=anchor, prompt=prompt, seed=seed,
            prefix='genj/hdr_outpaint/'+uuid.uuid4().hex, check_asset=check_asset)
        return await submit(subplan, graph)

    # The shared assembler blends overlap and extends only the final output;
    # original source audio is restored once by the HDR delivery stage.
    return await run_windows(kind='render', source=source, selection=expected, parts=parts,
        subplans=subplans, submit=submit_window, wait=wait, cancel=cancel, update=update,
        ffmpeg=ffmpeg, output=destination, source_audio=None, anchor=True)
