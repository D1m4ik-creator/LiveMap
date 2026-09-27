import { useEffect, useState, type FormEvent } from 'react';
import type { AdminCamera, AdminPlace, AdminRole, AdminSource, CameraInput, PlaybackType } from '../types';
import { StatusBadge } from '../ui/StatusBadge';
import { CameraChecks } from './CameraChecks';
import { apiDate, changedFields, localDate } from './formUtils';

type CameraForm = { place_id: number; source_id: number; name: string; playback_type: PlaybackType; validLocal: string; embedLocal: string };
function initial(selected: AdminCamera | null, places: AdminPlace[], sources: AdminSource[]): CameraForm {
  return selected ? {
    place_id: selected.place_id, source_id: selected.source_id, name: selected.name,
    playback_type: selected.playback_type, validLocal: localDate(selected.valid_until),
    embedLocal: localDate(selected.embed_verified_at),
  } : { place_id: places[0]?.id ?? 0, source_id: sources[0]?.id ?? 0, name: '', playback_type: 'iframe', validLocal: '', embedLocal: '' };
}

export function CameraEditor({ selected, places, sources, role, token, busy, onSave, onPublish, onDelete }: {
  selected: AdminCamera | null; places: AdminPlace[]; sources: AdminSource[]; token: string;
  role: AdminRole; busy: boolean;
  onSave: (body: CameraInput | (Partial<CameraInput> & { embed_verified_at?: string | null }), id?: number) => Promise<void>;
  onPublish: (id: number, published: boolean) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}) {
  const [form, setForm] = useState<CameraForm>(() => initial(selected, places, sources));
  useEffect(() => setForm(initial(selected, places, sources)), [selected, places.length, sources.length]);
  const set = <K extends keyof CameraForm>(key: K, value: CameraForm[K]) => setForm((old) => ({ ...old, [key]: value }));
  const toBody = (current: CameraForm) => ({
    place_id: current.place_id, source_id: current.source_id, name: current.name,
    playback_type: current.playback_type,
    valid_until: selected && current.validLocal === localDate(selected.valid_until)
      ? selected.valid_until : apiDate(current.validLocal),
    embed_verified_at: selected && current.embedLocal === localDate(selected.embed_verified_at)
      ? selected.embed_verified_at : apiDate(current.embedLocal),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const body = toBody(form);
    const original = selected ? toBody(initial(selected, places, sources)) : null;
    if (original) void onSave(changedFields(original, body), selected!.id);
    else {
      const { embed_verified_at: _unused, ...createBody } = body;
      void onSave(createBody);
    }
  };
  const source = sources.find((item) => item.id === form.source_id);
  const place = places.find((item) => item.id === form.place_id);
  const original = selected ? toBody(initial(selected, places, sources)) : null;
  const dirty = original !== null && Object.keys(changedFields(original, toBody(form))).length > 0;
  const now = Date.now();
  const issues: string[] = [];
  if (!place) issues.push('Выберите место');
  if (!source) issues.push('Выберите источник');
  if (source && !source.is_approved) issues.push('Источник не одобрен');
  if (source && !source.stream_url) issues.push('У источника нет URL потока');
  if (source?.secret_ref) issues.push('Нужен медиашлюз для секретного источника');
  if (source?.permission_expires_at && Date.parse(source.permission_expires_at) <= now) issues.push('Разрешение источника истекло');
  if (form.playback_type === 'rtsp') issues.push('RTSP требует медиашлюз');
  if (form.playback_type === 'iframe' && source && !source.embed_host) issues.push('Укажите домен iframe');
  if (form.playback_type === 'iframe' && (!selected?.embed_verified_at || Date.parse(selected.embed_verified_at) < now - 7 * 86_400_000)) issues.push('Проверьте встраивание в браузере за последние 7 дней');
  if (form.validLocal && new Date(form.validLocal).getTime() <= now) issues.push('Срок актуальности камеры истёк');
  if (dirty) issues.push('Сначала сохраните изменения формы');
  const publishable = issues.length === 0;
  return <form className="admin-form" onSubmit={submit}>
    <div className="form-grid">
      <div className="field wide"><label htmlFor="camera-name">Название камеры</label><input id="camera-name" required minLength={2} value={form.name} onChange={(e) => set('name', e.target.value)} /></div>
      <div className="field"><label htmlFor="camera-place">Место</label><select id="camera-place" required value={form.place_id} onChange={(e) => set('place_id', Number(e.target.value))}><option value={0} disabled>Выберите место</option>{places.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></div>
      <div className="field"><label htmlFor="camera-source">Источник</label><select id="camera-source" required value={form.source_id} onChange={(e) => set('source_id', Number(e.target.value))}><option value={0} disabled>Выберите источник</option>{sources.map((item) => <option value={item.id} key={item.id}>{item.owner_name} #{item.id}</option>)}</select></div>
      <div className="field"><label htmlFor="camera-type">Тип воспроизведения</label><select id="camera-type" value={form.playback_type} onChange={(e) => set('playback_type', e.target.value as PlaybackType)}><option value="iframe">iframe</option><option value="hls">HLS</option><option value="rtsp">RTSP (только черновик)</option></select></div>
      <div className="field"><label htmlFor="camera-valid">Срок актуальности</label><input id="camera-valid" type="datetime-local" value={form.validLocal} onChange={(e) => set('validLocal', e.target.value)} /></div>
      {selected && form.playback_type === 'iframe' && <div className="field wide"><label htmlFor="camera-embed">Когда вручную проверено встраивание</label><input id="camera-embed" type="datetime-local" value={form.embedLocal} onChange={(e) => set('embedLocal', e.target.value)} /><small>Укажите время только после проверки плеера в браузере. Действует семь дней.</small></div>}
    </div>
    <div className="admin-preview"><strong>Предпросмотр публикации</strong><br />{place?.name ?? 'Место не выбрано'} · {source?.owner_name ?? 'Источник не выбран'} · {form.playback_type.toUpperCase()}
      {selected && <div className="admin-preview-status">Камера: {selected.is_published ? 'опубликована' : 'черновик'} <StatusBadge status={selected.status} /> {selected.last_error_code && <span>Ошибка: {selected.last_error_code}</span>}</div>}
      {issues.length > 0 ? <ul className="publication-issues">{issues.map((issue) => <li key={issue}>{issue}</li>)}</ul> : <p>Условия для публикации заполнены. После проверки worker камера появится на карте при свежем статусе online.</p>}
    </div>
    <div className="admin-form-actions"><button className="admin-primary" type="submit" disabled={busy || !form.place_id || !form.source_id}>{selected ? 'Сохранить камеру' : 'Создать черновик'}</button>{selected && role === 'admin' && <><button type="button" className="admin-secondary" disabled={busy || (!selected.is_published && !publishable)} onClick={() => void onPublish(selected.id, !selected.is_published)}>{selected.is_published ? 'Снять с публикации' : 'Опубликовать камеру'}</button><button type="button" className="admin-secondary admin-danger" disabled={busy} onClick={() => { if (window.confirm(`Удалить камеру «${selected.name}»?`)) void onDelete(selected.id); }}>Удалить</button></>}</div>
    {selected && role === 'admin' && <CameraChecks token={token} cameraId={selected.id} />}
  </form>;
}
