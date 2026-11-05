import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export function validatePlaywrightImage(image, lock) {
  const match =
    typeof image === 'string' &&
    image.match(
      /^mcr\.microsoft\.com\/playwright:v(\d+\.\d+\.\d+)-[a-z][a-z0-9-]*@sha256:[a-f0-9]{64}$/,
    );
  if (!match) {
    throw new Error(
      'Expected an official Playwright image with an exact version, OS tag, and SHA256 digest.',
    );
  }
  const version = match[1];
  for (const name of ['@playwright/test', 'playwright', 'playwright-core']) {
    const key = `node_modules/${name}`;
    const lockedVersion = lock?.packages?.[key]?.version;
    if (typeof lockedVersion !== 'string' || !lockedVersion) {
      throw new Error(
        `Missing package version for ${key} in package-lock.json.`,
      );
    }
    if (lockedVersion !== version) {
      throw new Error(
        `Playwright image ${version} does not match ${key} lock version ${lockedVersion}; update the browser CI image and package lock together.`,
      );
    }
  }
  return version;
}

if (
  process.argv[1] &&
  pathToFileURL(process.argv[1]).href === import.meta.url
) {
  try {
    const lockPath =
      process.argv[2] ?? new URL('../package-lock.json', import.meta.url);
    const lock = JSON.parse(readFileSync(lockPath, 'utf8'));
    const version = validatePlaywrightImage(
      process.env.PLAYWRIGHT_CI_IMAGE,
      lock,
    );
    console.log(`Playwright image and locked SDK packages match (${version}).`);
  } catch (error) {
    console.error(`Playwright image compatibility failed: ${error.message}`);
    process.exitCode = 1;
  }
}
