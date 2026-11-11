import {openZuraStudio} from '../studio.js';

// Compatibility import for older integrations. Zura Studio owns the shell,
// commands and projects; there is no separate Paintout application entry.
export function openPaintout(){return openZuraStudio('paintout');}
