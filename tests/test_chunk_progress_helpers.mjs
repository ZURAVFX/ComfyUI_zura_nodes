import assert from 'node:assert/strict';
import {elapsedSeconds, findRenderer, formatStatus} from '../web/chunk_progress_helpers.js';

const renderer = {id: 1111, type: 'TrendStudioWan22Chunks'};
const host = {id: 1114, type: 'NativeSubgraph', subgraph: {nodes: [renderer]}};
const graph = {nodes: [host]};
assert.deepEqual(findRenderer(graph, '1114:1111'), {node: renderer, host});
assert.match(formatStatus({state: 'chunk_started', shot: 2, shots: 3, chunk: 4, chunks: 9, completed_frames: 41, total_frames: 243}), /shot 2\/3 · loop 4\/9 · 41\/243 frames \(16%\)/);
assert.match(formatStatus({state: 'error', error: 'boom', completed_frames: 41, total_frames: 243}), /error: boom/);
assert.equal(formatStatus({state: 'preparing', stage: '  Encoding   prompt ', stage_started_at: 100, elapsed_seconds: 0,
  completed_frames: 12, total_frames: 243}, 106.8), 'Wan 2.2 preparing · Encoding prompt · 6s · 0/243 frames (0%)');
assert.equal(formatStatus({state: 'preparing', stage: 'Encoding negative prompt', elapsed_seconds: 61, total_frames: 243}, 106.8),
  'Wan 2.2 preparing · Encoding negative prompt · 1m 1s · 0/243 frames (0%)');
assert.equal(elapsedSeconds({state: 'preparing', stage_started_at: 100, elapsed_seconds: 4}, 102), 4);
assert.match(formatStatus({state: 'preparing', total_frames: 10}), /preparing · Preparing · 0\/10 frames \(0%\)/);
console.log('Wan 2.2 progress resolves native subgraph paths and formats shot/chunk/frame status.');
