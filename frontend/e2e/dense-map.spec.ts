import { expect, test } from '@playwright/test';

test.skip(process.env.DENSE_MAP_E2E !== '1', 'Manual dense-map measurement on a production build.');

test('500 точек: карта реагирует на масштабирование без потока bbox-запросов', async ({ page }) => {
  await page.route('https://tiles.openfreemap.org/styles/**', route => route.fulfill({ json: {
    version: 8, sources: {}, layers: [],
  } }));
  const points = Array.from({ length: 500 }, (_, i) => ({
    id: i + 1, slug: `dense-${i}`, name: `Точка ${i}`, city: 'Тестовый каталог',
    category: 'street', coordinates: [30 + (i % 25) * 5, 44 + Math.floor(i / 25)],
    camera_count: 1, online_count: 1, status: 'online',
  }));
  let requests = 0;
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/places?**', route => {
    requests++;
    if (Number(new URL(route.request().url()).searchParams.get('zoom')) < 3) {
      return route.fulfill({ json: { mode: 'clusters', points: [], truncated: false,
        clusters: [{ id: 'dense', coordinates: [90, 60], place_count: 550,
          camera_count: 550, online_count: 550, status: 'online' }],
      } });
    }
    return route.fulfill({ json: { mode: 'points', points, clusters: [], truncated: true } });
  });
  await page.goto('/');
  await expect(page.getByText('Загружаем карту России…', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Точки списком', exact: true }).click();
  await page.getByRole('button', { name: /Группа: 550.*Приблизить карту/ }).click();
  await expect(page.getByText('Слишком много точек. Приблизьте карту.', { exact: true })).toBeVisible();
  const before = requests;
  const sampling = page.evaluate(() => new Promise<{ frames: number; p95_ms: number; max_ms: number }>(resolve => {
    const deltas: number[] = [];
    const start = performance.now();
    let last = start;
    function tick(now: number) {
      deltas.push(now - last); last = now;
      if (now - start < 2000) requestAnimationFrame(tick);
      else {
        deltas.sort((a, b) => a - b);
        resolve({ frames: deltas.length, p95_ms: deltas[Math.floor(deltas.length * .95)], max_ms: Math.max(...deltas) });
      }
    }
    requestAnimationFrame(tick);
  }));
  await page.getByRole('button', { name: 'Увеличить масштаб', exact: true }).click({ clickCount: 3, delay: 80 });
  const pacing = await sampling;
  expect(requests - before).toBeLessThanOrEqual(2);
  expect(errors).toEqual([]);
  await page.getByRole('button', { name: 'Точки списком', exact: true }).click();
  await expect(page.locator('#visible-places button').filter({ hasText: /^Точка \d/ })).toHaveCount(500);
  await test.info().attach('dense-map-measurement', {
    body: JSON.stringify({ points: 500, zoom_requests: requests - before, ...pacing }),
    contentType: 'application/json',
  });
  console.log(JSON.stringify({ dense_map: { points: 500, zoom_requests: requests - before, ...pacing } }));
});
