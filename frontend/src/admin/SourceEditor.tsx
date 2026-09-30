import { useEffect, useState, type FormEvent } from 'react';
import type { AdminRole, AdminSource, SourceInput } from '../types';
import { apiDate, changedFields, localDate } from './formUtils';

type SourceForm = Omit<SourceInput, 'permission_reviewed_at' | 'permission_expires_at'> & { reviewLocal: string; expiryLocal: string };
const emptySource: SourceForm = {
  owner_name: '', public_page_url: '', stream_url: '', secret_ref: null, attribution: '',
  permission_note: '', permission_evidence_url: null, embed_host: null, removal_contact: null,
  reviewLocal: '', expiryLocal: '',
};

function initial(selected: AdminSource | null): SourceForm {
  return selected ? {
    owner_name: selected.owner_name, public_page_url: selected.public_page_url,
    stream_url: selected.stream_url, secret_ref: selected.secret_ref,
    attribution: selected.attribution, permission_note: selected.permission_note,
    permission_evidence_url: selected.permission_evidence_url, embed_host: selected.embed_host,
    removal_contact: selected.removal_contact,
    reviewLocal: localDate(selected.permission_reviewed_at), expiryLocal: localDate(selected.permission_expires_at),
  } : emptySource;
}

export function SourceEditor({ selected, role, busy, onSave, onApprove, onDelete }: {
  selected: AdminSource | null; role: AdminRole; busy: boolean;
  onSave: (body: SourceInput | Partial<SourceInput>, id?: number) => Promise<void>;
  onApprove: (id: number, approved: boolean) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}) {
  const [form, setForm] = useState<SourceForm>(emptySource);
  useEffect(() => setForm(initial(selected)), [selected]);
  const set = <K extends keyof SourceForm>(key: K, value: SourceForm[K]) => setForm((old) => ({ ...old, [key]: value }));
  const toBody = (current: SourceForm): SourceInput => ({
    owner_name: current.owner_name, public_page_url: current.public_page_url,
    stream_url: current.stream_url || null, secret_ref: current.secret_ref,
    attribution: current.attribution, permission_note: current.permission_note,
    permission_evidence_url: current.permission_evidence_url, embed_host: current.embed_host,
    removal_contact: current.removal_contact,
    permission_reviewed_at: selected && current.reviewLocal === localDate(selected.permission_reviewed_at)
      ? selected.permission_reviewed_at : apiDate(current.reviewLocal),
    permission_expires_at: selected && current.expiryLocal === localDate(selected.permission_expires_at)
      ? selected.permission_expires_at : apiDate(current.expiryLocal),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const body = toBody(form);
    const original = selected ? toBody(initial(selected)) : null;
    void onSave(original ? changedFields(original, body) : body, selected?.id);
  };
  const current = toBody(form);
  const dirty = selected !== null && Object.keys(changedFields(toBody(initial(selected)), current)).length > 0;
  const approvalIssues: string[] = [];
  if (!current.stream_url) approvalIssues.push('Заполните URL потока или iframe');
  if (!current.permission_evidence_url) approvalIssues.push('Укажите ссылку на условия или разрешение');
  if (!current.permission_reviewed_at) approvalIssues.push('Укажите, когда условия проверены');
  if (!current.removal_contact) approvalIssues.push('Укажите контакт для удаления');
  if (current.permission_expires_at && Date.parse(current.permission_expires_at) <= Date.now()) {
    approvalIssues.push('Срок разрешения истёк. Проверьте дату окончания разрешения');
  }
  if (dirty) approvalIssues.push('Сначала сохраните изменения источника');
  const canApprove = approvalIssues.length === 0;
  return <form className="admin-form" onSubmit={submit}>
    <div className="form-grid">
      <div className="field wide"><label htmlFor="source-owner">Владелец</label><input id="source-owner" required minLength={2} value={form.owner_name} onChange={(e) => set('owner_name', e.target.value)} /></div>
      <div className="field wide"><label htmlFor="source-page">Публичная страница источника</label><input id="source-page" required type="url" value={form.public_page_url} onChange={(e) => set('public_page_url', e.target.value)} /></div>
      <div className="field wide"><label htmlFor="source-stream">URL потока или iframe</label><input id="source-stream" value={form.stream_url ?? ''} onChange={(e) => set('stream_url', e.target.value || null)} /></div>
      <div className="field"><label htmlFor="source-host">Домен iframe</label><input id="source-host" placeholder="rutube.ru" value={form.embed_host ?? ''} onChange={(e) => set('embed_host', e.target.value || null)} /></div>
      <div className="field"><label htmlFor="source-secret">Ссылка на секрет</label><input id="source-secret" placeholder="SOURCE_TOKEN" value={form.secret_ref ?? ''} onChange={(e) => set('secret_ref', e.target.value || null)} /></div>
      <div className="field wide"><label htmlFor="source-attribution">Подпись источника</label><input id="source-attribution" required minLength={2} value={form.attribution} onChange={(e) => set('attribution', e.target.value)} /></div>
      <div className="field wide"><label htmlFor="source-note">Основание для показа</label><textarea id="source-note" required minLength={5} value={form.permission_note} onChange={(e) => set('permission_note', e.target.value)} /></div>
      <div className="field wide"><label htmlFor="source-evidence">Ссылка на условия или разрешение</label><input id="source-evidence" type="url" value={form.permission_evidence_url ?? ''} onChange={(e) => set('permission_evidence_url', e.target.value || null)} /></div>
      <div className="field"><label htmlFor="source-review">Когда условия проверены</label><input id="source-review" type="datetime-local" value={form.reviewLocal} onChange={(e) => set('reviewLocal', e.target.value)} /></div>
      <div className="field"><label htmlFor="source-expiry">Срок разрешения</label><input id="source-expiry" type="datetime-local" value={form.expiryLocal} onChange={(e) => set('expiryLocal', e.target.value)} /><small>Дата окончания разрешения, а не дата проверки. Оставьте пустым, если у разрешения нет срока окончания.</small></div>
      <div className="field wide"><label htmlFor="source-contact">Контакт для удаления</label><input id="source-contact" value={form.removal_contact ?? ''} onChange={(e) => set('removal_contact', e.target.value || null)} /></div>
    </div>
    {selected && <div className="admin-preview">Источник {selected.is_approved ? 'одобрен' : 'ожидает проверки'}. Изменение URL, владельца или условий автоматически снимет одобрение и публикацию связанных камер. Одобрение выполняется отдельным действием после проверки.
      {approvalIssues.length > 0 && <ul className="publication-issues" aria-label="Что требуется для одобрения">{approvalIssues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
    </div>}
    <div className="admin-form-actions"><button className="admin-primary" type="submit" disabled={busy}>{selected ? 'Сохранить источник' : 'Создать черновик'}</button>{selected && role === 'admin' && <><button type="button" className="admin-secondary" disabled={busy || (!selected.is_approved && !canApprove)} onClick={() => void onApprove(selected.id, !selected.is_approved)}>{selected.is_approved ? 'Отозвать одобрение' : 'Одобрить источник'}</button><button type="button" className="admin-secondary admin-danger" disabled={busy} onClick={() => { if (window.confirm(`Удалить источник «${selected.owner_name}»?`)) void onDelete(selected.id); }}>Удалить</button></>}</div>
  </form>;
}
