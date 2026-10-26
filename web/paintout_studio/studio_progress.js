// Progress describes the current stage, never an invented whole-job percentage.
export function durationLabel(seconds) {
  const value=Math.max(0,Math.ceil(Number(seconds)||0));
  if(value<60)return `${value}s`;
  const minutes=Math.floor(value/60), remainder=value%60;
  return remainder?`${minutes}m ${remainder}s`:`${minutes}m`;
}
