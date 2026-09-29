import { expect, test, type Page } from '@playwright/test';

const place = {
  id: 1, slug: 'test-square', name: 'Тестовая площадь', address: 'Центральная улица',
  city: 'Москва', region: 'Москва', category: 'square', coordinates: [37.62, 55.75],
  cameras: [{
    id: 7, name: 'Площадь сейчас', playback_type: 'iframe', status: 'online',
    last_checked_at: new Date().toISOString(), last_success_at: new Date().toISOString(),
    availability_note: null, source_name: 'Публичный источник',
    source_page_url: 'https://ipeye.ru/', attribution: 'Публичный источник',
    playback_url: 'https://ipeye.ru/test-player', embed_host: 'ipeye.ru',
  }],
};

async function mockCatalog(page: Page, online = true) {
  await page.route('https://tiles.openfreemap.org/styles/**', (route) => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ version: 8, sources: {}, layers: [] }),
  }));
  await page.route('https://ipeye.ru/test-player', (route) => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><title>Тестовый эфир</title><p>LIVE</p>',
  }));
  await page.route('**/api/v1/places**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/search')) return route.fulfill({ json: {
      suggestions: [{ kind: 'place', label: 'Тестовая площадь, Москва', coordinates: [37.62, 55.75], place_id: 1 }],
    } });
    if (url.pathname.endsWith('/1')) return route.fulfill({ json: {
      ...place, cameras: place.cameras.map((camera) => online ? camera : {
        ...camera, status: 'offline', playback_url: null, availability_note: 'Трансляция временно недоступна',
      }),
    } });
    return route.fulfill({ json: {
      mode: 'points', clusters: [], truncated: false,
      points: [{ id: 1, slug: place.slug, name: place.name, city: place.city,
        category: place.category, coordinates: place.coordinates, camera_count: 1,
        online_count: online ? 1 : 0, status: online ? 'online' : 'offline' }],
    } });
  });
}

test('production-карта загружает отдельный worker при строгой CSP', async ({ page }) => {
  await mockCatalog(page);
  await page.route('http://127.0.0.1:4173/', async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: {
      ...response.headers(),
      'content-security-policy': "default-src 'self'; script-src 'self'; worker-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' https:; img-src 'self' data: blob:",
    } });
  });
  const workerResponse = page.waitForResponse((response) =>
    /\/assets\/maplibre-gl-worker-[^/]+\.js$/.test(response.url()));
  await page.goto('/');
  expect((await workerResponse).ok()).toBe(true);
  await expect.poll(() => page.workers().length).toBeGreaterThan(0);
  expect(await page.workers()[0].evaluate(() => typeof self.postMessage)).toBe('function');
  await expect(page.getByText('Worker failed to load.', { exact: false })).toHaveCount(0);
});

test('поиск открывает место и плеер, закрытие возвращает к карточке', async ({ page }) => {
  await mockCatalog(page);
  await page.goto('/');
  await page.getByRole('combobox', { name: 'Поиск города, улицы или места' }).fill('Тестовая');
  await page.getByRole('option', { name: /Тестовая площадь/ }).click();
  await expect(page).toHaveURL(/\/place\/1/);
  await expect(page.getByRole('heading', { name: place.name })).toBeVisible();
  await page.getByRole('button', { name: /Площадь сейчас/ }).click();
  await expect(page).toHaveURL(/camera=7/);
  await expect(page.getByTitle('Площадь сейчас')).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: 'Закрыть трансляцию' }).click();
  await expect(page).not.toHaveURL(/camera=7/);
});

test('на мобильной ширине недоступный эфир не открывает поток', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockCatalog(page, false);
  await page.goto('/place/1');
  await expect(page.getByRole('heading', { name: place.name })).toBeVisible();
  await page.getByRole('button', { name: /Площадь сейчас/ }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Трансляция временно недоступна' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTitle('Площадь сейчас')).toHaveCount(0);
});

test('администратор публикует и снимает камеру с публикации', async ({ page }) => {
  let published = false;
  const now = new Date().toISOString();
  const adminPlace = { ...place, cameras: undefined, is_published: true, created_at: now, updated_at: now };
  const source = {
    id: 3, owner_name: 'Публичный источник', public_page_url: 'https://example.org/live',
    stream_url: 'https://example.org/live.m3u8', secret_ref: null, attribution: 'Публичный источник',
    permission_note: 'Разрешено для теста', permission_evidence_url: 'https://example.org/permission',
    permission_reviewed_at: now, embed_host: null, permission_expires_at: null,
    removal_contact: 'operator@example.org', is_approved: true, created_at: now, updated_at: now,
  };
  const camera = () => ({
    id: 7, place_id: 1, source_id: 3, name: 'Площадь сейчас', playback_type: 'hls',
    valid_until: null, is_published: published, status: 'online', last_checked_at: now,
    last_success_at: now, next_check_at: null, last_error_code: null, consecutive_failures: 0,
    embed_verified_at: null, unpublished_reason: null, created_at: now, updated_at: now,
  });
  await page.route('**/api/v1/admin/**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/login')) return route.fulfill({ json: {
      access_token: 'test-token', token_type: 'bearer', expires_at: now, role: 'admin',
    } });
    if (url.pathname.endsWith('/me')) return route.fulfill({ json: { id: 1, username: 'root', role: 'admin' } });
    if (url.pathname.endsWith('/places')) return route.fulfill({ json: [adminPlace] });
    if (url.pathname.endsWith('/sources')) return route.fulfill({ json: [source] });
    if (url.pathname.endsWith('/cameras')) return route.fulfill({ json: [camera()] });
    if (url.pathname.endsWith('/cameras/7/checks')) return route.fulfill({ json: [] });
    if (url.pathname.endsWith('/cameras/7') && route.request().method() === 'PATCH') {
      published = !published;
      return route.fulfill({ json: camera() });
    }
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'Not found' } } });
  });
  await page.goto('/admin');
  await page.getByLabel('Имя пользователя').fill('root');
  await page.getByLabel('Пароль').fill('test-password-123');
  await page.getByRole('button', { name: 'Войти' }).click();
  await page.getByRole('navigation', { name: 'Разделы панели' }).getByRole('button', { name: 'Камеры' }).click();
  await page.getByRole('button', { name: /Площадь сейчас/ }).click();
  await page.getByRole('button', { name: 'Опубликовать камеру' }).click();
  await expect(page.getByText('Камера опубликована')).toBeVisible();
  await page.getByRole('button', { name: 'Снять с публикации' }).click();
  await expect(page.getByText('Камера снята с публикации')).toBeVisible();
  expect(published).toBe(false);
});
