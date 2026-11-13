// Operation drafts belong to one shot, not to the shared video backend mode.
export const REMOVE_PROMPT = 'remove the ';
const defaults = () => ({paint:'', remove:REMOVE_PROMPT, replace:''});
export function platePromptDrafts(state) {
  const source = String(state.source || '');
  const current = state.platePrompts;
  if (current?.version === 1 && current.source === source && current.values) return current;
  // Older platePrompt/cleanupPrompt/prompts fields have no operation provenance.
  // Do not guess which operation they belonged to when migrating a saved shot.
  return state.platePrompts = {version:1, source, values:defaults()};
}
export function platePrompt(state, action) {
  const values = platePromptDrafts(state).values;
  return typeof values[action] === 'string' ? values[action] : defaults()[action] || '';
}
export function savePlatePrompt(state, action, value) {
  if (!['paint','remove','replace'].includes(action)) return;
  platePromptDrafts(state).values[action] = String(value ?? '');
}
