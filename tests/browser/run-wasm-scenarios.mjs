import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const path = process.argv[2];
assert(path, 'usage: node tools/run-wasm-scenarios.mjs <simulator.wasm> [--browser]');
const bytes = new Uint8Array(await readFile(path));

// This function is serialized into a real browser realm by Playwright.
// It must not close over Node APIs or a JS reimplementation of the scenarios.
async function execute(binary) {
  const { instance } = await WebAssembly.instantiate(new Uint8Array(binary), {});
  const e = instance.exports;
  const count = e.scenario_count();
  if (count === 0) throw new Error('empty Rust scenario registry');
  const names = [];
  for (let index = 0; index < count; index++) {
    const name = new TextDecoder().decode(new Uint8Array(
      e.memory.buffer, e.scenario_name_ptr(index), e.scenario_name_len(index),
    ));
    if (!name || names.includes(name)) throw new Error('invalid/duplicate scenario name');
    try {
      if (e.scenario_run(index) !== 1) throw new Error('scenario did not succeed');
    } catch (error) {
      throw new Error(`Rust scenario ${index} (${name}) failed: ${error}`);
    }
    names.push(name);
  }
  if (e.scenario_run(count) !== 0) throw new Error('invalid index accepted');
  return names;
}

const nodeResults = await execute(bytes);
for (const name of nodeResults) console.log(`Node PASS ${name}`);
if (process.argv.includes('--browser')) {
  const { chromium } = await import('playwright');
  const browser = await chromium.launch({ headless: true });
  try {
    console.log(`Chromium ${browser.version()}`);
    const page = await browser.newPage();
    const browserResults = await page.evaluate(execute, Array.from(bytes));
    assert.deepEqual(browserResults, nodeResults);
    for (const name of browserResults) console.log(`Chromium PASS ${name}`);
  } finally {
    await browser.close();
  }
}
console.log(`${nodeResults.length} shared Rust scenarios passed`);
