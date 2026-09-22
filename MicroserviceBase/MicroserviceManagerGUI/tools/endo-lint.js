#!/usr/bin/env node
/**
 * endo-lint: check Bench Endoskeleton manifests before they ship.
 *
 *   node tools/endo-lint.js <file-or-dir> [...] [--shell 2.3.0] [--warn-as-error]
 *
 * Files named component.json or plugin.json are linted; a directory is
 * searched for them. Components found together are also checked against
 * each other (duplicate ids). Exit code 1 on any error, so it fails CI.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const contract = require('../web/js/endo/contract/lint.js');

const CONTRACT_DIR = path.join(__dirname, '..', 'web', 'js', 'endo', 'contract');
const componentSchema = JSON.parse(fs.readFileSync(path.join(CONTRACT_DIR, 'component.schema.json'), 'utf-8'));
const pluginSchema = JSON.parse(fs.readFileSync(path.join(CONTRACT_DIR, 'plugin.schema.json'), 'utf-8'));

function usage(code) {
  console.log('usage: node tools/endo-lint.js <component.json|plugin.json|dir> [...] [--shell X.Y.Z] [--warn-as-error]');
  process.exit(code);
}

const args = process.argv.slice(2);
let shell = contract.SHELL_VERSION;
let warnAsError = false;
const targets = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--shell') shell = args[++i];
  else if (args[i] === '--warn-as-error') warnAsError = true;
  else if (args[i] === '-h' || args[i] === '--help') usage(0);
  else targets.push(args[i]);
}
if (!targets.length) usage(2);

function collect(p, out) {
  let st;
  try { st = fs.statSync(p); } catch (e) { console.error('not found: ' + p); process.exitCode = 1; return; }
  if (st.isDirectory()) {
    for (const name of fs.readdirSync(p)) {
      if (name === 'node_modules' || name.startsWith('.')) continue;
      collect(path.join(p, name), out);
    }
  } else if (/(^|[\\/])(component|plugin)\.json$/.test(p)) {
    out.push(p);
  } else if (targets.includes(p)) {
    out.push(p);   // named explicitly: lint whatever it is
  }
}

const files = [];
targets.forEach((t) => collect(t, files));

let errors = 0;
let warnings = 0;
const components = [];
for (const file of files) {
  let manifest;
  try {
    // Windows tools (PowerShell 5.1, older Notepad) write a UTF-8 BOM.
    manifest = JSON.parse(fs.readFileSync(file, 'utf-8').replace(/^﻿/, ''));
  } catch (e) {
    console.log(file + '\n  S ERROR (file): not valid JSON: ' + e.message);
    errors++;
    continue;
  }
  const isPlugin = manifest && typeof manifest === 'object' && 'plugin' in manifest;
  const issues = isPlugin
    ? contract.lintPlugin(manifest, { schema: pluginSchema, shell })
    : contract.lintComponent(manifest, { schema: componentSchema, shell });
  if (!isPlugin) components.push(manifest);
  const e = issues.filter((i) => i.severity === 'error').length;
  const w = issues.length - e;
  errors += e;
  warnings += w;
  console.log(file + (issues.length ? '' : '  ok'));
  issues.forEach((i) => console.log('  ' + contract.formatIssue(i)));
}

// Duplicates across the components found together
const dupes = contract.lintComponents(components, { shell })
  .filter((i) => i.message === 'duplicate component id on this bench');
dupes.forEach((i) => { console.log('  ' + contract.formatIssue(i)); errors++; });

console.log('\n' + files.length + ' manifest(s), ' + errors + ' error(s), ' + warnings + ' warning(s), shell ' + shell);
if (errors || (warnAsError && warnings)) process.exitCode = 1;
