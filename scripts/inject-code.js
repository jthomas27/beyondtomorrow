#!/usr/bin/env node
// Compatibility entry point. The maintained implementation uses httpx in Python.
const {spawnSync} = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const result = spawnSync(path.join(root, '.venv/bin/python'),
  [path.join(__dirname, 'deploy_ghost_theme.py'), '--apply', ...process.argv.slice(2)],
  {cwd: root, stdio: 'inherit'});
if (result.error) console.error('Theme command could not start; check the project virtual environment.');
process.exit(result.status ?? 1);
