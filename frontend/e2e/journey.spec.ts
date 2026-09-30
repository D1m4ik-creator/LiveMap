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

test('одобрение источника объясняет истёкший срок и требует сохранения исправлений', async ({ page }) => {
  const now = new Date().toISOString();
  let approvalRequests = 0;
  let source = {
    id: 3, owner_name: 'Тестовый источник', public_page_url: 'https://example.org/live',
    stream_url: 'https://example.org/live.m3u8', secret_ref: null, attribution: 'Тестовый источник',
    permission_note: 'Только для браузерного теста', permission_evidence_url: 'https://example.org/permission',
    permission_reviewed_at: now, embed_host: null, permission_expires_at: '2000-01-01T00:00:00Z' as string | null,
    removal_contact: 'operator@example.org', is_approved: false, created_at: now, updated_at: now,
  };
  await page.route('**/api/v1/admin/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/login')) return route.fulfill({ json: {
      access_token: 'source-test-token', token_type: 'bearer', expires_at: new Date(Date.now() + 8 * 3_600_000).toISOString(), role: 'admin',
    } });
    if (path.endsWith('/me')) return route.fulfill({ json: { id: 1, username: 'root', role: 'admin' } });
    if (path.endsWith('/sources')) return route.fulfill({ json: [source] });
    if (path.endsWith('/places') || path.endsWith('/cameras')) return route.fulfill({ json: [] });
    if (path.endsWith('/sources/3') && route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON();
      if ('is_approved' in body) {
        approvalRequests++;
        expect(source.permission_expires_at).toBeNull();
        expect(Object.keys(body)).toEqual(['is_approved']);
      }
      source = { ...source, ...body };
      return route.fulfill({ json: source });
    }
    return route.fulfill({ status: 404 });
  });
  await page.goto('/admin');
  await page.getByLabel('Имя пользователя').fill('root');
  await page.getByLabel('Пароль').fill('test-password-123');
  await page.getByRole('button', { name: 'Войти' }).click();
  await page.getByRole('navigation', { name: 'Разделы панели' }).getByRole('button', { name: 'Источники' }).click();
  await page.getByRole('button', { name: /Тестовый источник https/ }).click();
  const approval = page.getByRole('button', { name: 'Одобрить источник', exact: true });
  await expect(approval).toBeDisabled();
  await expect(page.getByRole('list', { name: 'Что требуется для одобрения' })).toContainText('Срок разрешения истёк');
  await page.getByLabel('Срок разрешения', { exact: true }).fill('');
  await expect(approval).toBeDisabled();
  await expect(page.getByRole('list', { name: 'Что требуется для одобрения' })).toContainText('Сначала сохраните изменения');
  await page.getByRole('button', { name: 'Сохранить источник', exact: true }).click();
  await expect(approval).toBeEnabled();
  await approval.click();
  await expect(page.getByText('Источник одобрен', { exact: true })).toBeVisible();
  expect(approvalRequests).toBe(1);
});

test('сессия администратора переживает обновление, сохранение и ошибки камеры', async ({ page }) => {
  let published = false;
  let name = 'Площадь сейчас';
  let patchStatus = 200;
  let meStatus = 200;
  let authorized = true;
  let logins = 0;
  let cameraPatches = 0;
  let navigations = 0;
  page.on('framenavigated', (frame) => { if (frame === page.mainFrame()) navigations++; });
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
    id: 7, place_id: 1, source_id: 3, name, playback_type: 'hls',
    valid_until: null, is_published: published, status: 'online', last_checked_at: now,
    last_success_at: now, next_check_at: null, last_error_code: null, consecutive_failures: 0,
    embed_verified_at: null, unpublished_reason: null, created_at: now, updated_at: now,
  });
  await page.route('**/api/v1/admin/**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/login')) {
      logins++;
      return route.fulfill({ json: {
        access_token: 'test-token', token_type: 'bearer', expires_at: new Date(Date.now() + 8 * 3_600_000).toISOString(), role: 'admin',
      } });
    }
    expect(route.request().headers().authorization).toBe('Bearer test-token');
    if (url.pathname.endsWith('/logout')) return route.fulfill({ status: 204 });
    if (!authorized) return route.fulfill({ status: 401, json: { error: { code: 'unauthorized', message: 'Authentication required' } } });
    if (url.pathname.endsWith('/me')) return route.fulfill({ status: meStatus, json: meStatus === 200
      ? { id: 1, username: 'root', role: 'admin' }
      : { error: { code: 'unavailable', message: 'Temporarily unavailable' } } });
    if (url.pathname.endsWith('/places')) return route.fulfill({ json: [adminPlace] });
    if (url.pathname.endsWith('/sources')) return route.fulfill({ json: [source] });
    if (url.pathname.endsWith('/cameras')) return route.fulfill({ json: [camera()] });
    if (url.pathname.endsWith('/cameras/7/checks')) return route.fulfill({ json: [] });
    if (url.pathname.endsWith('/cameras/7') && route.request().method() === 'PATCH') {
      cameraPatches++;
      if (patchStatus !== 200) return route.fulfill({ status: patchStatus, json: { error: { code: 'test_error', message: 'Ошибка сохранения' } } });
      const body = route.request().postDataJSON();
      if ('is_published' in body) published = body.is_published;
      if ('name' in body) name = body.name;
      return route.fulfill({ json: camera() });
    }
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'Not found' } } });
  });
  await page.goto('/admin');
  await page.getByLabel('Имя пользователя').fill('root');
  await page.getByLabel('Пароль').fill('test-password-123');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('heading', { name: 'Управление каталогом' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Управление каталогом' })).toBeVisible();
  expect(logins).toBe(1);
  await page.getByRole('navigation', { name: 'Разделы панели' }).getByRole('button', { name: 'Камеры' }).click();
  await page.getByRole('button', { name: /Площадь сейчас/ }).click();
  await page.getByRole('button', { name: 'Проверить трансляцию' }).click();
  await expect(page.getByRole('region', { name: 'Предпросмотр камеры' })).toBeVisible();
  await expect(page.locator('video')).toHaveCount(1);
  await expect(page.getByText('Предпросмотр черновика · камера ещё не опубликована')).toBeVisible();
  await page.getByRole('button', { name: 'Закрыть трансляцию' }).click();
  await expect(page.getByRole('region', { name: 'Предпросмотр камеры' })).toHaveCount(0);
  expect(cameraPatches).toBe(0);
  expect(published).toBe(false);
  const beforeSave = navigations;
  await page.getByLabel('Название камеры').fill('Обновлённая камера');
  await page.getByRole('button', { name: 'Сохранить камеру' }).click();
  await expect(page.getByText('Камера сохранена')).toBeVisible();
  await expect(page.getByLabel('Название камеры')).toHaveValue('Обновлённая камера');
  expect(navigations).toBe(beforeSave);
  await page.getByRole('button', { name: 'Опубликовать камеру' }).click();
  await expect(page.getByText('Камера опубликована')).toBeVisible();
  await page.getByRole('button', { name: 'Снять с публикации' }).click();
  await expect(page.getByText('Камера снята с публикации')).toBeVisible();
  expect(published).toBe(false);
  for (const status of [409, 500]) {
    patchStatus = status;
    await page.getByLabel('Название камеры').fill(`Попытка ${status}`);
    await page.getByRole('button', { name: 'Сохранить камеру' }).click();
    await expect(page.getByRole('alert')).toContainText('Ошибка сохранения');
    await expect(page.getByRole('heading', { name: 'Управление каталогом' })).toBeVisible();
    expect(logins).toBe(1);
  }
  meStatus = 503;
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('Не удалось проверить сессию');
  meStatus = 200;
  await page.getByRole('button', { name: 'Повторить', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Управление каталогом' })).toBeVisible();
  expect(logins).toBe(1);
  await page.getByRole('button', { name: 'Выйти', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Вход в LiveMap' })).toBeVisible();
  await page.getByLabel('Имя пользователя').fill('root');
  await page.getByLabel('Пароль').fill('test-password-123');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('heading', { name: 'Управление каталогом' })).toBeVisible();
  authorized = false;
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Вход в LiveMap' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('Сессия завершилась');
  authorized = true;
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Вход в LiveMap' })).toBeVisible();
  await page.clock.install();
  await page.getByLabel('Имя пользователя').fill('root');
  await page.getByLabel('Пароль').fill('test-password-123');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('heading', { name: 'Управление каталогом' })).toBeVisible();
  await page.clock.fastForward(8 * 3_600_000);
  await expect(page.getByRole('heading', { name: 'Вход в LiveMap' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('Сессия завершилась');
});
