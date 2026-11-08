#!/usr/bin/env node
/**
 * Generate a per-clip grade (.drx) from grade params.
 *
 * A thin stdin/stdout bridge so the Python server can use the offline DRX generator
 * in `resolve-advanced` (the `drx` tool's `generate` action) instead of a second
 * implementation of the format.
 *
 * Input (stdin, JSON): { gradeParams: {...}, metadata?: {...}, outputPath: "..." }
 *   gradeParams uses the drx tool's value space (space:'ui' by default: Resolve
 *   panel numbers — lift/gamma ~±0.05, gain ~1.0, saturation 0-100 with 50 neutral).
 * Output (stdout, JSON): { ok, outputPath, bytes, warnings: [...] }
 * On failure: { ok: false, error } and a non-zero exit.
 */

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const server = path.join(here, '..', 'resolve-advanced', 'server');

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

async function main() {
  const request = JSON.parse((await readStdin()) || '{}');
  const { gradeParams, metadata = {}, outputPath } = request;
  if (!gradeParams || typeof gradeParams !== 'object') throw new Error('gradeParams must be an object');
  if (!outputPath) throw new Error('outputPath is required');
  // File URLs, not paths: the Windows ESM loader refuses `C:\...` (same fix as author_interchange.mjs).
  const libs = await import(pathToFileURL(path.join(server, 'libs.mjs')).href);
  const tool = await import(pathToFileURL(path.join(server, 'tools', 'drx.mjs')).href);
  const warnings = [];
  const out = await libs.drxGenerator().generateDRX(tool.normalizeGradeParams(gradeParams, warnings), metadata);
  const content = typeof out === 'string' ? out : out?.content || out?.drxContent;
  if (!content) throw new Error('the generator returned no .drx content');
  await fs.mkdir(path.dirname(path.resolve(outputPath)), { recursive: true });
  await fs.writeFile(outputPath, content);
  process.stdout.write(JSON.stringify({ ok: true, outputPath, bytes: Buffer.byteLength(content), warnings }));
}

main().catch((error) => {
  process.stdout.write(JSON.stringify({ ok: false, error: String(error?.message || error) }));
  process.exit(1);
});
