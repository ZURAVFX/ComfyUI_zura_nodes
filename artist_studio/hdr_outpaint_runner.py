"""Private coordinator for a reviewed, bounded LTX HDR outpaint.

The host owns graph submission, artifact verification, cleanup, and the UI.
This is not a public Studio route until the complete path has been tested.
"""
import asyncio

from .hdr_outpaint_experiment import build_reviewed_sdr_first_stage, build_reviewed_sdr_first_composite


async def run_reviewed_hdr_outpaint(*, source, selection, review_key, colour_space,
                                   has_audio, prompt, seed, identity, check_asset,
                                   submit, wait, cancel, update, cleanup):
    """Run two bounded graphs sequentially and publish only verified outputs.

    ``wait`` must verify its own artifact and return an input path for the SDR
    pass or the validated final delivery for the HDR pass. ``cleanup`` may only
    remove the intermediate owned by this job; final outputs remain available.
    """
    if not isinstance(identity, str) or not identity.isalnum() or len(identity) > 64:
        raise ValueError('Choose a valid HDR outpaint job identity.')
    active = None
    intermediate = None

    async def run_pass(name, graph):
        nonlocal active
        update(name)
        pending = asyncio.create_task(submit(name, graph))
        try:
            active = await asyncio.shield(pending)
        except asyncio.CancelledError:
            try:
                active = await pending
            except Exception:
                pass
            raise
        if not active:
            raise RuntimeError('The HDR outpaint pass did not return a job ID.')
        result = await wait(name, active)
        active = None
        if not result:
            raise RuntimeError('The HDR outpaint pass did not return its expected output.')
        return result

    try:
        # Asset verification may hash large videos or access network storage;
        # keep it off Comfy's event loop so progress and Cancel remain responsive.
        stage = await asyncio.to_thread(build_reviewed_sdr_first_stage, source, selection, review_key=review_key,
            colour_space=colour_space, prompt=prompt, seed=seed,
            prefix='genj/hdr_outpaint/' + identity, check_asset=check_asset)
        intermediate = await run_pass('outpaint', stage)
        # Revalidate the source, approved geometry and colour before the second
        # pass; a changed selection must not reuse an earlier approval.
        final = await asyncio.to_thread(build_reviewed_sdr_first_composite, source, selection, intermediate,
            review_key=review_key, colour_space=colour_space, has_audio=has_audio,
            seed=seed, prefix='hdr_outpaint_' + identity, check_asset=check_asset)
        return await run_pass('hdr', final)
    except BaseException:
        if active is not None:
            await cancel(active)
        raise
    finally:
        if intermediate is not None:
            await cleanup(intermediate)
