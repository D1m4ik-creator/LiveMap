import { useQuery, useQueryClient } from '@tanstack/react-query';
import { LogOut, Plus, Radio } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { adminApi } from '../api/client';
import type { AdminRole, CameraInput, PlaceInput, SourceInput } from '../types';
import { StatusBadge } from '../ui/StatusBadge';
import { ActionButton } from '../ui/ActionButton';
import { FormField } from '../ui/FormField';
import { TabBar } from '../ui/TabBar';
import { CameraEditor } from './CameraEditor';
import { ImportPanel } from './ImportPanel';
import { PlaceEditor } from './PlaceEditor';
import { SourceEditor } from './SourceEditor';

type Tab = 'places' | 'sources' | 'cameras' | 'import' | 'audit';
const tabs: { id: Tab; label: string }[] = [
  { id: 'places', label: 'Места' }, { id: 'sources', label: 'Источники' },
  { id: 'cameras', label: 'Камеры' }, { id: 'import', label: 'Импорт' },
  { id: 'audit', label: 'Журнал' },
];

export function AdminPage() {
  const queryClient = useQueryClient();
  const [token, setToken] = useState<string | null>(null);
  const [role, setRole] = useState<AdminRole | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [tab, setTab] = useState<Tab>('places');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const me = useQuery({ queryKey: ['admin', 'me'], enabled: Boolean(token), queryFn: () => adminApi.me(token!) });
  const places = useQuery({ queryKey: ['admin', 'places'], enabled: Boolean(token), queryFn: () => adminApi.places(token!) });
  const sources = useQuery({ queryKey: ['admin', 'sources'], enabled: Boolean(token), queryFn: () => adminApi.sources(token!) });
  const cameras = useQuery({ queryKey: ['admin', 'cameras'], enabled: Boolean(token), queryFn: () => adminApi.cameras(token!) });
  const audit = useQuery({ queryKey: ['admin', 'audit'], enabled: Boolean(token) && role === 'admin' && tab === 'audit', queryFn: () => adminApi.audit(token!) });

  const run = async <T,>(operation: () => Promise<T>, success: string, after?: (value: T) => void) => {
    setBusy(true); setError(null); setMessage(null);
    try {
      const result = await operation();
      after?.(result);
      setMessage(success);
      await queryClient.invalidateQueries({ queryKey: ['admin'] });
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Операция не выполнена'); }
    finally { setBusy(false); }
  };
  const login = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const result = await adminApi.login(username, password);
      setToken(result.access_token); setRole(result.role); setPassword('');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось войти'); }
    finally { setBusy(false); }
  };
  const logout = async () => {
    if (token) await adminApi.logout(token).catch(() => undefined);
    setToken(null); setRole(null); setSelectedId(null);
    queryClient.removeQueries({ queryKey: ['admin'] });
  };
  const changeTab = (next: Tab) => { setTab(next); setSelectedId(null); setError(null); setMessage(null); };
  const savePlace = (body: PlaceInput | Partial<PlaceInput>, id?: number) => run(
    () => id ? adminApi.updatePlace(token!, id, body) : adminApi.createPlace(token!, body as PlaceInput),
    id ? 'Место сохранено' : 'Черновик места создан', (item) => setSelectedId(item.id),
  );
  const saveSource = (body: SourceInput | Partial<SourceInput>, id?: number) => run(
    () => id ? adminApi.updateSource(token!, id, body) : adminApi.createSource(token!, body as SourceInput),
    id ? 'Источник сохранён' : 'Черновик источника создан', (item) => setSelectedId(item.id),
  );
  const saveCamera = (body: CameraInput | (Partial<CameraInput> & { embed_verified_at?: string | null }), id?: number) => run(
    () => id ? adminApi.updateCamera(token!, id, body) : adminApi.createCamera(token!, body as CameraInput),
    id ? 'Камера сохранена' : 'Черновик камеры создан', (item) => setSelectedId(item.id),
  );

  if (!token || !role) return <div className="admin-page"><div className="admin-shell"><header className="admin-header"><Link className="brand-logo" to="/"><span className="brand-symbol"><Radio size={20} /></span><span>LIVE<span>MAP</span></span></Link><div className="admin-header-actions"><Link to="/">← Вернуться к карте</Link></div></header><form className="admin-card login-card" onSubmit={(event) => void login(event)}><div className="admin-kicker">ПАНЕЛЬ УПРАВЛЕНИЯ</div><h1>Вход в LiveMap</h1><p>Доступ для редакторов и администраторов каталога. Первого пользователя создают локальной командой `uv run livemap-admin create-user`.</p><FormField id="login-user" label="Имя пользователя"><input id="login-user" autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} /></FormField><div style={{ marginTop: 14 }}><FormField id="login-password" label="Пароль"><input id="login-password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></FormField></div>{error && <div className="admin-notice error" role="alert">{error}</div>}<ActionButton variant="primary" type="submit" disabled={busy} style={{ marginTop: 20, width: '100%' }}>{busy ? 'Проверяем…' : 'Войти'}</ActionButton></form></div></div>;

  const list = tab === 'places' ? places.data : tab === 'sources' ? sources.data : tab === 'cameras' ? cameras.data : [];
  const selectedPlace = places.data?.find((item) => item.id === selectedId) ?? null;
  const selectedSource = sources.data?.find((item) => item.id === selectedId) ?? null;
  const selectedCamera = cameras.data?.find((item) => item.id === selectedId) ?? null;
  const listError = places.error || sources.error || cameras.error || me.error;

  return <div className="admin-page"><div className="admin-shell">
    <header className="admin-header"><Link className="brand-logo" to="/"><span className="brand-symbol"><Radio size={20} /></span><span>LIVE<span>MAP</span></span></Link><div className="admin-header-actions"><span>{me.data?.username ?? username} · {role}</span><Link to="/">Открыть карту</Link><button onClick={() => void logout()}><LogOut size={14} /> Выйти</button></div></header>
    <div className="admin-intro"><span className="admin-kicker">LIVE MAP / CONTROL ROOM</span><h1>Управление каталогом</h1><p>Места, проверенные источники, камеры и история изменений в одном рабочем пространстве.</p></div>
    <TabBar items={tabs.filter((item) => item.id !== 'audit' || role === 'admin')} value={tab} onChange={changeTab} label="Разделы панели" />
    {message && <div className="admin-notice" role="status">{message}</div>}
    {(error || listError) && <div className="admin-notice error" role="alert">{error || (listError instanceof Error ? listError.message : 'Не удалось загрузить данные')} <button className="admin-secondary" onClick={() => void queryClient.invalidateQueries({ queryKey: ['admin'] })}>Повторить</button></div>}
    {(tab === 'places' || tab === 'sources' || tab === 'cameras') && <div className="admin-grid">
      <section className="admin-card"><div className="admin-card-head"><h2>{tab === 'places' ? 'Места' : tab === 'sources' ? 'Источники' : 'Камеры'}</h2><button className="admin-secondary" onClick={() => setSelectedId(null)}><Plus size={14} /> Новый черновик</button></div><div className="admin-list">{list?.map((item) => <button className={`admin-item ${selectedId === item.id ? 'active' : ''}`} key={item.id} onClick={() => setSelectedId(item.id)}><span><strong>{'slug' in item ? item.name : 'owner_name' in item ? item.owner_name : item.name}</strong><small>{'city' in item ? item.city : 'playback_type' in item ? `${item.playback_type.toUpperCase()} · место #${item.place_id}` : item.public_page_url}</small></span><span className="admin-list-state">{'playback_type' in item ? <>{item.is_published ? 'ОПУБЛИКОВАНА' : 'ЧЕРНОВИК'}<StatusBadge status={item.status} /></> : 'is_approved' in item ? item.is_approved ? 'ОДОБРЕН' : 'ЧЕРНОВИК' : item.is_published ? 'ОПУБЛИКОВАНО' : 'ЧЕРНОВИК'}</span></button>)}{!list && <div className="admin-empty">Загрузка каталога…</div>}{list?.length === 0 && <div className="admin-empty">Записей пока нет.</div>}</div></section>
      <section className="admin-card"><div className="admin-card-head"><h2>{selectedId ? `Запись #${selectedId}` : 'Новый черновик'}</h2><span>Изменения попадут в журнал</span></div>
        {tab === 'places' && <PlaceEditor selected={selectedPlace} cameras={cameras.data ?? []} role={role} busy={busy} onSave={savePlace} onPublish={(id, published) => run(() => adminApi.updatePlace(token, id, { is_published: published }), published ? 'Место опубликовано' : 'Место снято с публикации')} onDelete={(id) => run(() => adminApi.deletePlace(token, id), 'Место удалено', () => setSelectedId(null))} />}
        {tab === 'sources' && <SourceEditor selected={selectedSource} role={role} busy={busy} onSave={saveSource} onApprove={(id, approved) => run(() => adminApi.updateSource(token, id, { is_approved: approved }), approved ? 'Источник одобрен' : 'Одобрение отозвано')} onDelete={(id) => run(() => adminApi.deleteSource(token, id), 'Источник удалён', () => setSelectedId(null))} />}
        {tab === 'cameras' && <CameraEditor selected={selectedCamera} places={places.data ?? []} sources={sources.data ?? []} role={role} token={token} busy={busy} onSave={saveCamera} onPublish={(id, published) => run(() => adminApi.updateCamera(token, id, { is_published: published }), published ? 'Камера опубликована' : 'Камера снята с публикации')} onDelete={(id) => run(() => adminApi.deleteCamera(token, id), 'Камера удалена', () => setSelectedId(null))} />}
      </section>
    </div>}
    {tab === 'import' && <ImportPanel token={token} role={role} onApplied={() => void queryClient.invalidateQueries({ queryKey: ['admin'] })} />}
    {tab === 'audit' && role === 'admin' && <section className="admin-card"><div className="admin-card-head"><h2>Журнал изменений</h2><span>Все события</span></div><div className="audit-list">{audit.data?.map((item) => <div className="audit-item" key={item.id}><time>{new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(item.created_at))}</time><span>{item.summary}</span><small>{item.action} · {item.entity_type} #{item.entity_id}</small></div>)}{audit.isPending && <div className="admin-empty">Загружаем журнал…</div>}{audit.data?.length === 0 && <div className="admin-empty">Событий нет.</div>}</div></section>}
  </div></div>;
}
