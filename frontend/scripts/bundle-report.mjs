import { readFileSync, readdirSync, statSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { join } from 'node:path';

const checkMode = process.argv.includes('--check');
const assetsDir = new URL('../dist/assets/', import.meta.url);

const budgets = [
  { pattern: /^editor-.*\.js$/, maxBytes: 2_000_000 },
  { pattern: /^charts-.*\.js$/, maxBytes: 700_000 },
  { pattern: /^markdown-.*\.js$/, maxBytes: 700_000 },
  { pattern: /^react-.*\.js$/, maxBytes: 700_000 },
  { pattern: /^vendor-.*\.js$/, maxBytes: 700_000 },
  { pattern: /^drag-drop-.*\.js$/, maxBytes: 500_000 },
  { pattern: /.*\.js$/, maxBytes: 500_000 },
];

function budgetFor(fileName) {
  return budgets.find((budget) => budget.pattern.test(fileName));
}

function formatBytes(bytes) {
  return `${(bytes / 1024).toFixed(1)} KiB`;
}

const chunks = readdirSync(assetsDir)
  .filter((fileName) => fileName.endsWith('.js'))
  .map((fileName) => {
    const filePath = join(assetsDir.pathname, fileName);
    const size = statSync(filePath).size;
    const gzipSize = gzipSync(readFileSync(filePath)).byteLength;
    return { fileName, size, gzipSize, budget: budgetFor(fileName) };
  })
  .sort((left, right) => right.size - left.size);

console.log('Largest frontend chunks:');
for (const chunk of chunks.slice(0, 10)) {
  const max = chunk.budget ? ` / budget ${formatBytes(chunk.budget.maxBytes)}` : '';
  console.log(`- ${chunk.fileName}: ${formatBytes(chunk.size)} raw, ${formatBytes(chunk.gzipSize)} gzip${max}`);
}

const failures = chunks.filter((chunk) => chunk.budget && chunk.size > chunk.budget.maxBytes);
if (checkMode && failures.length > 0) {
  console.error('\nBundle budget exceeded:');
  for (const failure of failures) {
    console.error(`- ${failure.fileName}: ${formatBytes(failure.size)} > ${formatBytes(failure.budget.maxBytes)}`);
  }
  process.exitCode = 1;
}
