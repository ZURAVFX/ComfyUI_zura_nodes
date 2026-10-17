// Progress describes the current stage, never an invented whole-job percentage.
export function durationLabel(seconds) {
  const value=Math.max(0,Math.ceil(Number(seconds)||0));
  if(value<60)return `${value}s`;
  const minutes=Math.floor(value/60), remainder=value%60;
  return remainder?`${minutes}m ${remainder}s`:`${minutes}m`;
}

export function stageProgress(progress, fallback={}) {
  const p=progress||{}, queued=p.state==="queued" || (!progress && fallback.state==="queued");
  const percent=typeof p.stage_percent==="number" && Number.isFinite(p.stage_percent)
    ?Math.max(0,Math.min(100,p.stage_percent)):null;
  const remaining=typeof p.stage_remaining_seconds==="number" && Number.isFinite(p.stage_remaining_seconds)
    ?Math.max(0,p.stage_remaining_seconds):null;
  const elapsed=typeof p.stage_elapsed_seconds==="number" && Number.isFinite(p.stage_elapsed_seconds)
    ?Math.max(0,p.stage_elapsed_seconds):null;
  const steps=Number.isInteger(p.step)&&Number.isInteger(p.total_steps)&&p.total_steps>0
    ?`Step ${Math.max(0,p.step)} of ${p.total_steps}`:null;
  const title=p.stage_label || fallback.label || "Preparing your shot";
  const detail=queued
    ?(Number.isInteger(p.queue_position)&&p.queue_position>0?`Queue position ${p.queue_position}`:"Waiting in the ComfyUI queue")
    :p.state==="complete"?"Stage complete"
    :remaining!==null && p.eta_confidence==="measured"?`About ${durationLabel(remaining)} left in this stage`
    :fallback.state==="waiting"?"Waiting for the previous model to unload"
    :"Estimating time for this stage…";
  return {title,detail,percent:queued?null:percent,
    meta:[steps,elapsed!==null && !queued?`${durationLabel(elapsed)} elapsed`:null].filter(Boolean).join(" · ")};
}
