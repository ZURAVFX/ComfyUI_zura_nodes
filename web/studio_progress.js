// Progress describes the current stage, never an invented whole-job percentage.
export function durationLabel(seconds) {
  const value=Math.max(0,Math.ceil(Number(seconds)||0));
  if(value<60)return `${value}s`;
  const minutes=Math.floor(value/60), remainder=value%60;
  return remainder?`${minutes}m ${remainder}s`:`${minutes}m`;
}

export function stageProgress(progress, fallback={}) {
  // A phase handoff can arrive before the next native progress snapshot. Never
  // carry the previous sampler's percentage or ETA into the next model load.
  const stale=progress && ((progress.action_id && fallback.actionId && progress.action_id!==fallback.actionId)
    || (progress.action_stage && fallback.stage && progress.action_stage!==fallback.stage));
  const p=stale?{}:progress||{};
  const queued=p.state==="queued" || fallback.state==="queued";
  const waiting=fallback.state==="waiting" || p.state==="waiting";
  const preparing=waiting || p.state==="preparing" || stale;
  const active=!queued && !preparing;
  const percent=active && typeof p.stage_percent==="number" && Number.isFinite(p.stage_percent)
    ?Math.max(0,Math.min(100,p.stage_percent)):null;
  const remaining=typeof p.stage_remaining_seconds==="number" && Number.isFinite(p.stage_remaining_seconds)
    ?Math.max(0,p.stage_remaining_seconds):null;
  const elapsed=typeof p.stage_elapsed_seconds==="number" && Number.isFinite(p.stage_elapsed_seconds)
    ?Math.max(0,p.stage_elapsed_seconds):null;
  const steps=active && Number.isInteger(p.step)&&Number.isInteger(p.total_steps)&&p.total_steps>0
    ?`${fallback.stage==='wan21_relight'?'Current section · ':''}Step ${Math.max(0,p.step)} of ${p.total_steps}`:null;
  const title=fallback.label || p.stage_label || "Preparing your shot";
  // Older backends label every sampler/decoder as video. Keep image-stage
  // wording correct immediately, including before the backend is restarted.
  let activity=p.stage_label && p.stage_label!==title?p.stage_label:null;
  if(fallback.stage==='design' && activity)activity=activity.replace(/H3 video model/g,'image model').replace(/H3 text encoder/g,'image text encoder').replace(/H3 decoder/g,'image decoder').replace(/H3 speed adapter/g,'image adapter').replace(/\bvideo\b/gi,'image');
  const detail=queued
    ?(Number.isInteger(p.queue_position)&&p.queue_position>0?`Queue position ${p.queue_position}`:"Waiting in the ComfyUI queue")
    :waiting?"Switching models…"
    :p.state==="complete"?"Stage complete"
    :preparing?(activity || "Loading and preparing…")
    :remaining!==null && p.eta_confidence==="measured"?[activity,`About ${durationLabel(remaining)} left in this step`].filter(Boolean).join(" · ")
    :activity || (percent!==null?"Processing · estimating time…":"Loading and preparing…");
  return {title,detail,percent:queued?null:percent,
    meta:[steps,elapsed>0 && !queued?`${durationLabel(elapsed)} elapsed`:null].filter(Boolean).join(" · ")};
}
