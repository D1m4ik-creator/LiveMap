import { expect, test } from '@playwright/test';

test.skip(process.env.LIVE_STREAM_E2E !== '1', 'External provider integration is opt-in; CI uses deterministic journeys.');

for (const source of [
  { name: 'Интернациональная улица', url: 'https://impulssrv.12bit.ru/ramdisk/cam9015/live.m3u8' },
  { name: 'Судостроительная улица', url: 'https://fl-4.telecoma.tv/sud25gd_1/tracks-v1/index.fmp4.m3u8' },
]) {
  test(`${source.name}: эфир проходит несколько окон и восстанавливается после обрыва`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.route('https://tiles.openfreemap.org/styles/**', route => route.fulfill({
      json: { version: 8, sources: {}, layers: [] },
    }));
    await page.route('**/api/v1/places**', route => route.fulfill({ json: {
      id: 1, slug: 'hls-integration', name: source.name, city: 'Тест эфира', region: 'Россия',
      category: 'street', coordinates: [76.6, 66], cameras: [{
        id: 15, name: source.name, playback_type: 'hls', status: 'online',
        playback_url: source.url, source_name: 'Публичный оператор',
        source_page_url: 'https://cam-world.ru/', attribution: 'Публичный оператор',
        last_checked_at: new Date().toISOString(), last_success_at: new Date().toISOString(),
        availability_note: null, embed_host: null,
      }], mode: 'points', points: [], clusters: [], truncated: false,
    } }));
    let interrupted = false;
    let playlistLoads = 0;
    await page.route(source.url, route => {
      playlistLoads++;
      return interrupted ? route.abort('failed') : route.continue();
    });
    await page.goto('/place/1?camera=15');
    const video = page.locator('video');
    await expect.poll(() => video.evaluate(v => (v as HTMLVideoElement).videoWidth), { timeout: 45_000 }).toBeGreaterThan(0);
    await expect(page.getByText('Прямой эфир · шкала показывает обновляемый буфер', { exact: false })).toBeVisible();
    const start = await video.evaluate(v => (v as HTMLVideoElement).currentTime);
    await expect.poll(() => video.evaluate(v => (v as HTMLVideoElement).currentTime), { timeout: 75_000 }).toBeGreaterThan(start + 40);
    expect(playlistLoads).toBeGreaterThan(3);
    interrupted = true;
    await page.waitForTimeout(18_000);
    interrupted = false;
    const resume = await video.evaluate(v => (v as HTMLVideoElement).currentTime);
    await expect.poll(() => video.evaluate(v => (v as HTMLVideoElement).currentTime), { timeout: 45_000 }).toBeGreaterThan(resume + 5);
    expect(await video.evaluate(v => (v as HTMLVideoElement).ended)).toBe(false);
    await page.getByRole('button', { name: 'К прямому эфиру', exact: true }).click();
    await test.info().attach('hls-live-proof', { body: JSON.stringify({ source: source.name, playlistLoads, start, resume }), contentType: 'application/json' });
  });
}
