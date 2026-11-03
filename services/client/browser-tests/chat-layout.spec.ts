import type { Locator } from '@playwright/test';
import { test, expect, type APIRequest } from './fixtures';
import { expectControlReachable, expectControlsUnclipped, expectDocumentContained, expectMainContained } from './geometry';
import { chatDetail, chatMessage, chatRoom } from './chatFixture';

async function transcriptGeometry(transcript: Locator) {
  return transcript.evaluate(element => {
    const style = getComputedStyle(element);
    return { usableHeight: element.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom),
      top: element.scrollTop, bottom: element.scrollHeight - element.scrollTop - element.clientHeight };
  });
}

test('Reachability rejects a clipped panel before automatic scrolling can conceal it', async ({ page }) => {
  await page.setContent('<div id="panel" style="height:20px;overflow:hidden"><button style="margin-top:80px">Clipped action</button></div>');
  await expect(expectControlReachable(page.getByRole('button', { name: 'Clipped action' })))
    .rejects.toThrow('Controls must not depend on programmatically scrolling a clipped panel');
  expect(await page.locator('#panel').evaluate(element => element.scrollTop)).toBe(0);
});

for (const height of [900, 600, 500]) {
  test(`Chat controls and local transcript remain usable at height ${height}`, async ({ page, fixtureAPI }, testInfo) => {
    await page.setViewportSize({ width: page.viewportSize()!.width, height });
    const room = chatRoom();
    const rooms = [room, ...Array.from({ length: 9 }, (_, index) => chatRoom({ id: index + 2,
      topic: `${'Release review context and ownership '.repeat(5)}${index + 2}`.slice(0, 200) }))];
    let messages = Array.from({ length: 30 }, (_, index) => chatMessage(index + 1,
      index === 0 ? { author: 'release_review_agent_with_extended_context' } : {}));
    fixtureAPI.get('/api/chat', { items: rooms, total: 27 });
    fixtureAPI.get('/api/chat/config', { participants: ['Kimi', 'Qwen'] });
    fixtureAPI.get('/api/chat/1', ({ url }: APIRequest) => chatDetail(room, messages, Number(url.searchParams.get('after_message_id') || 0)));
    fixtureAPI.mock('POST', '/api/chat/1/messages', ({ request }: APIRequest) => {
      expect(request.postDataJSON()).toEqual({ body: 'A clear next step.' });
      const message = chatMessage(31, { author: 'user', body: request.postDataJSON().body });
      messages = [...messages, message];
      return message;
    });
    await page.goto('/chat');
    const transcript = page.getByRole('region', { name: 'Chat messages', exact: true });
    await expect(transcript.locator('article')).toHaveCount(30);
    expect((await transcriptGeometry(transcript)).usableHeight).toBeGreaterThanOrEqual(120);
    expect(await transcript.evaluate(element => element.scrollHeight - element.clientHeight)).toBeGreaterThan(100);
    if (page.viewportSize()!.width >= 1024 && height === 900) {
      expect(await page.locator('#main-content').evaluate(element => element.scrollHeight - element.clientHeight)).toBeLessThanOrEqual(1);
    }
    const roomList = page.getByRole('complementary', { name: 'Chat rooms', exact: true });
    expect(await roomList.evaluate(element => element.scrollHeight - element.clientHeight)).toBeGreaterThan(100);
    await expectControlReachable(roomList.getByRole('button', { name: 'Next', exact: true }));
    await expectControlReachable(page.getByRole('button', { name: 'Edit', exact: true }));
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    const editTopic = page.getByRole('textbox', { name: 'Topic', exact: true });
    await expect(editTopic).toHaveValue(room.topic);
    await editTopic.fill('A clear review topic');
    await expectControlReachable(page.getByRole('button', { name: 'Cancel', exact: true }));
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(page.getByRole('heading', { name: room.topic })).toBeVisible();
    await transcript.scrollIntoViewIfNeeded();
    const outer = await page.locator('#main-content').evaluate(element => ({ main: element.scrollTop, document: document.documentElement.scrollTop }));
    await transcript.evaluate(element => { element.scrollTop = 0; });
    await expect.poll(async () => (await transcriptGeometry(transcript)).top).toBe(0);
    expect(await page.locator('#main-content').evaluate(element => ({ main: element.scrollTop, document: document.documentElement.scrollTop }))).toEqual(outer);
    const jump = page.getByRole('button', { name: 'Jump to latest', exact: true });
    await expectControlReachable(jump);
    await jump.click();
    await expect.poll(async () => (await transcriptGeometry(transcript)).bottom).toBeLessThanOrEqual(1);
    const draft = page.getByRole('textbox', { name: 'Message', exact: true });
    await expectControlReachable(draft);
    await draft.fill('A clear next step.');
    const send = page.getByRole('button', { name: 'Send', exact: true });
    await expectControlReachable(send);
    await send.click();
    await expect(transcript.getByText('A clear next step.', { exact: true })).toBeVisible();
    await expect(draft).toHaveValue('');
    await expect.poll(async () => (await transcriptGeometry(transcript)).bottom).toBeLessThanOrEqual(1);
    await page.getByRole('button', { name: '+ New Room', exact: true }).click();
    await page.getByRole('textbox', { name: 'Topic', exact: true }).fill('A new topic');
    await page.getByRole('textbox', { name: 'Context (optional)', exact: true }).fill('New room context');
    await expectControlReachable(page.getByRole('button', { name: 'Create Room', exact: true }));
    await expectControlReachable(page.getByRole('button', { name: 'Edit', exact: true }));
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await expect(page.getByRole('textbox', { name: 'Topic', exact: true })).toHaveCount(2);
    expect((await transcriptGeometry(transcript)).usableHeight).toBeGreaterThanOrEqual(120);
    const editCancel = page.locator('.chat-room .chat-create').getByRole('button', { name: 'Cancel', exact: true });
    await expectControlReachable(editCancel);
    await editCancel.click();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expectDocumentContained(page);
    await expectMainContained(page);
    await expectControlsUnclipped(page);
    await testInfo.attach('chat-geometry.json', { body: JSON.stringify(await transcriptGeometry(transcript)), contentType: 'application/json' });
  });
}

for (const height of [900, 500]) {
  test(`Chat preserves long topics and full context while keeping controls reachable at height ${height}`, async ({ page, fixtureAPI }) => {
    await page.setViewportSize({ width: page.viewportSize()!.width, height });
    const room = chatRoom({ topic: 'release_context_'.repeat(14).slice(0, 200), context: 'release_context_'.repeat(1334).slice(0, 20_000) });
    fixtureAPI.get('/api/chat', { items: [room], total: 1 });
    fixtureAPI.get('/api/chat/config', { participants: ['Kimi', 'Qwen'] });
    fixtureAPI.get('/api/chat/1', chatDetail(room, [chatMessage(1)]));
    await page.goto('/chat');
    await expect(page.getByRole('heading', { name: room.topic, exact: true })).toBeVisible();
    const context = page.getByRole('region', { name: 'Room context', exact: true });
    await expect(context).toHaveText(room.context);
    await context.scrollIntoViewIfNeeded();
    await context.focus();
    await context.press('End');
    await expect.poll(() => context.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
    expect((await transcriptGeometry(page.getByRole('region', { name: 'Chat messages', exact: true }))).usableHeight).toBeGreaterThanOrEqual(120);
    const edit = page.getByRole('button', { name: 'Edit', exact: true });
    await expectControlReachable(edit);
    await edit.click();
    await expect(page.getByRole('textbox', { name: 'Topic', exact: true })).toHaveValue(room.topic);
    await expect(page.getByRole('textbox', { name: 'Context (optional)', exact: true })).toHaveValue(room.context);
    const cancel = page.getByRole('button', { name: 'Cancel', exact: true });
    await expectControlReachable(cancel);
    await cancel.click();
    await expectDocumentContained(page);
    await expectMainContained(page);
    await expectControlsUnclipped(page);
  });
}

test('Chat keeps a reader’s position through polling and resets following when switching rooms', async ({ page, fixtureAPI }) => {
  const first = chatRoom();
  const second = chatRoom({ id: 2, topic: 'Another release review', context: '', state: 'closed' });
  let messages = Array.from({ length: 30 }, (_, index) => chatMessage(index + 1));
  fixtureAPI.get('/api/chat', { items: [first, second], total: 2 });
  fixtureAPI.get('/api/chat/config', { participants: ['Kimi', 'Qwen'] });
  fixtureAPI.get('/api/chat/1', ({ url }: APIRequest) => chatDetail(first, messages, Number(url.searchParams.get('after_message_id') || 0)));
  fixtureAPI.get('/api/chat/2', ({ url }: APIRequest) => chatDetail(second, [chatMessage(1, { room_id: 2, body: 'The second room transcript.' })],
    Number(url.searchParams.get('after_message_id') || 0)));
  await page.goto('/chat');
  const transcript = page.getByRole('region', { name: 'Chat messages', exact: true });
  await expect(transcript.locator('article')).toHaveCount(30);
  await expect.poll(async () => (await transcriptGeometry(transcript)).bottom).toBeLessThanOrEqual(1);
  await transcript.scrollIntoViewIfNeeded();
  await transcript.evaluate(element => { element.scrollTop = 0; });
  const jump = page.getByRole('button', { name: 'Jump to latest', exact: true });
  await expect(jump).toBeVisible();
  messages = [...messages, chatMessage(31, { body: 'Incoming context while reading earlier messages.' })];
  await expect(transcript.getByText('Incoming context while reading earlier messages.', { exact: true })).toBeAttached();
  expect((await transcriptGeometry(transcript)).top).toBe(0);
  await expectControlReachable(jump);
  await jump.click();
  await expect(transcript).toBeFocused();
  await expect.poll(async () => (await transcriptGeometry(transcript)).bottom).toBeLessThanOrEqual(1);
  messages = [...messages, chatMessage(32, { body: 'Following the latest incoming message.' })];
  await expect(transcript.getByText('Following the latest incoming message.', { exact: true })).toBeAttached();
  await expect.poll(async () => (await transcriptGeometry(transcript)).bottom).toBeLessThanOrEqual(1);
  const otherRoom = page.getByRole('button', { name: `${second.topic} closed`, exact: true });
  await expectControlReachable(otherRoom);
  await otherRoom.click();
  await expect(transcript.getByText('The second room transcript.', { exact: true })).toBeVisible();
  await expect(transcript.locator('article')).toHaveCount(1);
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Jump to latest', exact: true })).not.toBeVisible();
  await expectDocumentContained(page);
  await expectMainContained(page);
});
