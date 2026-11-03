import { test, expect, type APIRequest } from './fixtures';
import { harnessFixture } from './harnessFixture';
import { expectDocumentContained, expectMainContained } from './geometry';

interface Frame { handles: string[]; disabled: number; headerX: number[]; widths: number[]; tableY: number; scrollY: number; controlsHeight: number }
declare global {
  interface Window { harnessDragProof?: { running: boolean; frames: Frame[] } }
}

function gate() {
  let release!: () => void;
  const promise = new Promise<void>(resolve => { release = resolve; });
  return { promise, release };
}

test.use({ reducedMotion: 'no-preference' });

for (const mode of ['keyboard', 'pointer']) {
  test(`filtered page-two ${mode} dragging preserves handles and columns through deferred save and reread`, async ({ page, fixtureAPI }, testInfo) => {
    let items = [101, 104, 107].map(id => harnessFixture({ id, name: `visible_rule_${id}`, project: 'docs',
      sort_key: id * 10, updated_at: `2026-11-03T12:00:00.123${id}+00:00` }));
    const move = gate();
    const reread = gate();
    let moveStarted = false;
    let moveAccepted = false;
    let readStarted = false;
    let latestParams: Record<string, string> = {};
    const sdkErrors: string[] = [];
    page.on('console', message => {
      if (['error', 'warning'].includes(message.type()) && /@hello-pangea|drag handle|nested scroll|Invariant failed|setup problem/i.test(message.text())) sdkErrors.push(message.text());
    });
    fixtureAPI.get('/api/harness/items/rule', async ({ url }: APIRequest) => {
      latestParams = Object.fromEntries(url.searchParams);
      if (moveAccepted) expect(latestParams).toMatchObject({ name: 'visible', project: 'docs', offset: '10', limit: '10', sort: 'manual' });
      if (moveAccepted) { readStarted = true; await reread.promise; }
      return { items, total: 25 };
    });
    fixtureAPI.mock('POST', '/api/harness/items/rule/101/move', async ({ request }: APIRequest) => {
      expect(request.postDataJSON()).toEqual({ before_id: 107,
        expected_updated_at: items[0].updated_at, expected_anchor_updated_at: items[2].updated_at });
      moveStarted = true;
      await move.promise;
      items = [items[1], items[0], items[2]].map((item, index) => ({ ...item,
        sort_key: 10 + index, updated_at: '2026-11-03T12:00:01.654321+00:00' }));
      moveAccepted = true;
      return { id: 101, sort_key: 11, updated_at: items[1].updated_at };
    });
    await page.goto('/harness/rules');
    const region = page.getByRole('region', { name: 'Rules list', exact: true });
    const rows = region.locator('.harness-list-row');
    const handles = region.locator('button[data-rfd-drag-handle-draggable-id]');
    await expect(rows).toHaveCount(3);
    await page.getByRole('textbox', { name: 'Search', exact: true }).fill('visible');
    await page.getByRole('textbox', { name: 'Project scope', exact: true }).fill('docs');
    await expect.poll(() => latestParams).toMatchObject({ name: 'visible', project: 'docs' });
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect.poll(() => latestParams.offset).toBe('10');
    const handle = page.getByRole('button', { name: 'Reorder visible_rule_101', exact: true });
    await expect(handle).toBeEnabled();
    await handle.focus();
    await page.evaluate(() => {
      const proof = { running: true, frames: [] as Frame[] };
      window.harnessDragProof = proof;
      function sample() {
        const region = document.querySelector('.harness-list-scroll');
        const cells = [...document.querySelectorAll('.harness-list-header > div')];
        const handles = [...document.querySelectorAll<HTMLButtonElement>('button[data-rfd-drag-handle-draggable-id]')];
        if (region && cells.length) proof.frames.push({ handles: handles.map(node => node.dataset.rfdDragHandleDraggableId!).sort(),
          disabled: handles.filter(node => node.disabled).length, headerX: cells.map(node => node.getBoundingClientRect().x),
          widths: cells.map(node => node.getBoundingClientRect().width), tableY: region.getBoundingClientRect().y,
          scrollY: window.scrollY, controlsHeight: document.querySelector('.resource-controls')!.getBoundingClientRect().height });
        if (proof.running) requestAnimationFrame(sample);
      }
      sample();
    });
    if (mode === 'keyboard') {
      await page.keyboard.press('Space');
      await expect(rows.first()).toHaveCSS('position', 'fixed');
      await page.keyboard.press('ArrowDown');
      await page.keyboard.press('Space');
    } else {
      const box = (await handle.boundingBox())!;
      const row = (await rows.first().boundingBox())!;
      const x = box.x + box.width / 2;
      const y = box.y + box.height / 2;
      await page.mouse.move(x, y);
      await page.mouse.down();
      await page.mouse.move(x, y + 8, { steps: 3 });
      await expect(rows.first()).toHaveCSS('position', 'fixed');
      await page.mouse.move(x, y + row.height * 1.1, { steps: 10 });
      await page.mouse.up();
    }
    await expect.poll(() => moveStarted).toBe(true);
    await expect(handle).toBeDisabled();
    await expect(handles).toHaveCount(3);
    await expect(page.getByRole('textbox', { name: 'Search', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
    await page.waitForTimeout(100);
    move.release();
    await expect.poll(() => readStarted).toBe(true);
    await expect(handle).toBeDisabled();
    await expect(handles).toHaveCount(3);
    await page.waitForTimeout(100);
    reread.release();
    await expect(handle).toBeEnabled();
    await expect(rows.locator(':scope > div:nth-child(2)')).toHaveText(['visible_rule_104', 'visible_rule_101', 'visible_rule_107']);
    const frames = await page.evaluate(() => {
      window.harnessDragProof!.running = false;
      return window.harnessDragProof!.frames;
    });
    await testInfo.attach('drag-geometry.json', { body: JSON.stringify(frames), contentType: 'application/json' });
    expect(frames.length).toBeGreaterThan(5);
    expect(frames.some(frame => frame.disabled === 3)).toBe(true);
    const first = frames[0];
    for (const frame of frames) {
      expect(frame.handles).toEqual(['101', '104', '107']);
      expect(Math.abs(frame.tableY + frame.scrollY - first.tableY - first.scrollY)).toBeLessThanOrEqual(0.5);
      expect(Math.abs(frame.controlsHeight - first.controlsHeight)).toBeLessThanOrEqual(0.5);
      frame.headerX.forEach((value, index) => expect(Math.abs(value - first.headerX[index])).toBeLessThanOrEqual(0.5));
      frame.widths.forEach((value, index) => expect(Math.abs(value - first.widths[index])).toBeLessThanOrEqual(0.5));
    }
    const busy = frames.filter(frame => frame.disabled === 3);
    for (const frame of busy) {
      expect(Math.abs(frame.tableY - busy[0].tableY)).toBeLessThanOrEqual(0.5);
      expect(Math.abs(frame.scrollY - busy[0].scrollY)).toBeLessThanOrEqual(0.5);
    }
    expect(fixtureAPI.requests.filter(entry => entry.method === 'POST')).toHaveLength(1);
    expect(fixtureAPI.requests.filter(entry => entry.method === 'PUT')).toEqual([]);
    expect(sdkErrors).toEqual([]);
    await expectDocumentContained(page);
    await expectMainContained(page);
  });
}
