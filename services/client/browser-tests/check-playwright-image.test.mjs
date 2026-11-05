import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { validatePlaywrightImage } from './check-playwright-image.mjs';

const version = '1.2.3';
const image = `mcr.microsoft.com/playwright:v${version}-resolute@sha256:${'a'.repeat(64)}`;
const packageNames = ['@playwright/test', 'playwright', 'playwright-core'];
const script = fileURLToPath(
  new URL('./check-playwright-image.mjs', import.meta.url),
);
const lock = () => ({
  packages: Object.fromEntries(
    packageNames.map((name) => [`node_modules/${name}`, { version }]),
  ),
});

function runCli(t, contents, selectedImage = image) {
  const directory = mkdtempSync(
    join(tmpdir(), 'agent-smith-playwright-image-'),
  );
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const path = join(directory, 'package-lock.json');
  if (contents !== undefined) writeFileSync(path, contents);
  return spawnSync(process.execPath, [script, path], {
    cwd: directory,
    env: { PLAYWRIGHT_CI_IMAGE: selectedImage },
    encoding: 'utf8',
    timeout: 5000,
  });
}

test('accepts a matching image and all three exact locked SDK packages', () => {
  assert.equal(validatePlaywrightImage(image, lock()), version);
});

for (const name of packageNames) {
  test(`rejects a different locked ${name} version`, () => {
    const different = lock();
    different.packages[`node_modules/${name}`].version = '9.8.7';
    assert.throws(
      () => validatePlaywrightImage(image, different),
      new RegExp(name.replace('/', '\\/')),
    );
  });

  test(`rejects a missing locked ${name}`, () => {
    const incomplete = lock();
    delete incomplete.packages[`node_modules/${name}`];
    assert.throws(
      () => validatePlaywrightImage(image, incomplete),
      /missing|version/i,
    );
  });
}

test('rejects a missing package version and malformed lock structure', () => {
  const incomplete = lock();
  delete incomplete.packages['node_modules/playwright-core'].version;
  for (const value of [null, {}, { packages: null }, incomplete]) {
    assert.throws(
      () => validatePlaywrightImage(image, value),
      /package|version/i,
    );
  }
});

test('rejects missing, unpinned, nonofficial, and malformed image references', () => {
  for (const value of [
    undefined,
    '',
    'mcr.microsoft.com/playwright:latest',
    image.split('@')[0],
    image.replace('mcr.microsoft.com', 'example.invalid'),
    image.replace('v1.2.3-', 'v1.2-'),
    image.slice(0, -1),
    image + '\n',
    image + '\r\n',
  ]) {
    assert.throws(
      () => validatePlaywrightImage(value, lock()),
      /image|digest/i,
    );
  }
});

test('CLI succeeds using the supplied lock rather than its working directory', (t) => {
  const result = runCli(t, JSON.stringify(lock()));
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /1\.2\.3/);
  assert.equal(result.stderr, '');
});

test('CLI exits before tests on a mismatched SDK with actionable package details', (t) => {
  const different = lock();
  different.packages['node_modules/playwright-core'].version = '9.8.7';
  const result = runCli(t, JSON.stringify(different));
  assert.equal(result.status, 1);
  assert.match(result.stderr, /playwright-core/);
  assert.match(result.stderr, /1\.2\.3/);
  assert.match(result.stderr, /9\.8\.7/);
  assert.equal(result.stdout, '');
});

test('CLI rejects a missing image, invalid JSON, and an absent lock file', (t) => {
  for (const [contents, selectedImage] of [
    [JSON.stringify(lock()), ''],
    ['{ invalid JSON', image],
    [undefined, image],
  ]) {
    const result = runCli(t, contents, selectedImage);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /Playwright image compatibility failed/);
    assert.equal(result.stdout, '');
  }
});
