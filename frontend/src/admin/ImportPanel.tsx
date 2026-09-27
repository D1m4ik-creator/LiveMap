import { useState } from 'react';
import { adminApi } from '../api/client';
import type { AdminRole, ImportInput, ImportPreview, ImportResult } from '../types';
import { pluralRu } from '../ui/format';

export function ImportPanel({ token, role, onApplied }: { token: string; role: AdminRole; onApplied: () => void }) {
  const [body, setBody] = useState<ImportInput>({ format: 'geojson', content: '' });
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const update = (next: ImportInput) => { setBody(next); setPreview(null); setResult(null); setError(null); };
  const loadFile = async (file?: File) => {
    if (!file) return;
    if (file.size > 2_000_000) { setError('Файл больше 2 МБ'); return; }
    update({ format: file.name.toLowerCase().endsWith('.csv') ? 'csv' : 'geojson', content: await file.text() });
  };
  const run = async (apply: boolean) => {
    setBusy(true); setError(null);
    try {
      if (apply) { const next = await adminApi.applyImport(token, body); setResult(next); setPreview(null); onApplied(); }
      else { setPreview(await adminApi.previewImport(token, body)); setResult(null); }
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Ошибка импорта'); }
    finally { setBusy(false); }
  };
  return <section className="admin-card">
    <div className="admin-card-head"><h2>Импорт каталога</h2><span>CSV / GeoJSON · максимум 2 МБ</span></div>
    <div className="admin-import">
      <div className="field"><label htmlFor="import-file">Файл</label><input id="import-file" type="file" accept=".csv,.geojson,.json,text/csv,application/geo+json" onChange={(e) => void loadFile(e.target.files?.[0])} /></div>
      <div className="field"><label htmlFor="import-format">Формат</label><select id="import-format" value={body.format} onChange={(e) => update({ ...body, format: e.target.value as ImportInput['format'] })}><option value="geojson">GeoJSON</option><option value="csv">CSV</option></select></div>
      <div className="field"><label htmlFor="import-content">Содержимое для проверки</label><textarea id="import-content" value={body.content} onChange={(e) => update({ ...body, content: e.target.value })} placeholder="Вставьте содержимое файла или выберите файл выше" /></div>
      <div className="admin-form-actions"><button className="admin-secondary" disabled={busy || !body.content.trim()} onClick={() => void run(false)}>Проверить без записи</button><button className="admin-primary" disabled={busy || role !== 'admin' || !preview || preview.errors.length > 0 || preview.items.length === 0} onClick={() => void run(true)}>Применить импорт</button></div>
      {error && <div className="admin-notice error" role="alert">{error}</div>}
      {preview && <div className="admin-import-result" role="status"><strong>Предпросмотр: {preview.items.length} {pluralRu(preview.items.length, 'запись', 'записи', 'записей')}, {preview.errors.length} {pluralRu(preview.errors.length, 'ошибка', 'ошибки', 'ошибок')}</strong>{preview.errors.map((item) => <p key={`${item.row}-${item.message}`}>Строка {item.row}: {item.message}</p>)}{preview.items.map((item) => <p key={`${item.row}-${item.slug}`}>{item.action === 'create' ? 'Создать' : 'Обновить'} · {item.slug}{item.has_camera ? ' · камера как черновик' : ''}</p>)}</div>}
      {result && <div className="admin-notice">Импорт выполнен: создано {result.created}, обновлено {result.updated}, камер-черновиков {result.draft_cameras}.</div>}
    </div>
  </section>;
}
