import { useEffect, useState, type FormEvent } from 'react';
import type { AdminCamera, AdminPlace, AdminRole, PlaceInput } from '../types';
import { MapPicker } from './MapPicker';
import { changedFields } from './formUtils';

const emptyPlace: PlaceInput = {
  slug: '', name: '', address: null, city: '', region: '', category: 'square', coordinates: [37.6173, 55.7558],
};

export function PlaceEditor({ selected, cameras, role, busy, onSave, onPublish, onDelete }: {
  selected: AdminPlace | null; cameras: AdminCamera[]; role: AdminRole; busy: boolean;
  onSave: (body: PlaceInput | Partial<PlaceInput>, id?: number) => Promise<void>;
  onPublish: (id: number, published: boolean) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}) {
  const [form, setForm] = useState<PlaceInput>(emptyPlace);
  useEffect(() => { setForm(selected ? {
    slug: selected.slug, name: selected.name, address: selected.address, city: selected.city,
    region: selected.region, category: selected.category, coordinates: selected.coordinates,
  } : emptyPlace); }, [selected]);
  const set = <K extends keyof PlaceInput>(key: K, value: PlaceInput[K]) => setForm((old) => ({ ...old, [key]: value }));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const original = selected ? {
      slug: selected.slug, name: selected.name, address: selected.address, city: selected.city,
      region: selected.region, category: selected.category, coordinates: selected.coordinates,
    } : null;
    void onSave(original ? changedFields(original, form) : form, selected?.id);
  };
  const publishedCameras = cameras.filter((camera) => camera.place_id === selected?.id && camera.is_published).length;
  return (
    <form className="admin-form" onSubmit={submit}>
      <div className="form-grid">
        <div className="field"><label htmlFor="place-slug">Slug</label><input id="place-slug" required pattern="[a-z0-9]+(-[a-z0-9]+)*" value={form.slug} onChange={(e) => set('slug', e.target.value)} /></div>
        <div className="field"><label htmlFor="place-name">Название</label><input id="place-name" required minLength={2} value={form.name} onChange={(e) => set('name', e.target.value)} /></div>
        <div className="field"><label htmlFor="place-city">Город</label><input id="place-city" required minLength={2} value={form.city} onChange={(e) => set('city', e.target.value)} /></div>
        <div className="field"><label htmlFor="place-region">Регион</label><input id="place-region" required minLength={2} value={form.region} onChange={(e) => set('region', e.target.value)} /></div>
        <div className="field wide"><label htmlFor="place-address">Адрес</label><input id="place-address" value={form.address ?? ''} onChange={(e) => set('address', e.target.value || null)} /></div>
        <div className="field"><label htmlFor="place-category">Категория</label><select id="place-category" value={form.category} onChange={(e) => set('category', e.target.value)}><option value="square">Площадь</option><option value="bridge">Мост</option><option value="street">Улица</option><option value="park">Парк</option><option value="station">Вокзал</option><option value="other">Другое</option></select></div>
        <div className="field"><label htmlFor="place-lng">Долгота</label><input id="place-lng" required type="number" min="-180" max="180" step="any" value={form.coordinates[0]} onChange={(e) => set('coordinates', [Number(e.target.value), form.coordinates[1]])} /></div>
        <div className="field"><label htmlFor="place-lat">Широта</label><input id="place-lat" required type="number" min="-90" max="90" step="any" value={form.coordinates[1]} onChange={(e) => set('coordinates', [form.coordinates[0], Number(e.target.value)])} /></div>
        <div className="field wide"><label>Выбор точки на карте</label><MapPicker coordinates={form.coordinates} onChange={(value) => set('coordinates', value)} /><small>Нажмите на карту для выбора координат. Порядок: долгота, широта.</small></div>
      </div>
      {selected && <div className="admin-preview">Статус: {selected.is_published ? 'опубликовано' : 'черновик'}. Опубликованных камер: {publishedCameras}. Место появится на публичной карте после проверки доступности камеры.</div>}
      <div className="admin-form-actions"><button className="admin-primary" type="submit" disabled={busy}>{selected ? 'Сохранить место' : 'Создать черновик'}</button>{selected && role === 'admin' && <><button type="button" className="admin-secondary" disabled={busy || (!selected.is_published && publishedCameras === 0)} onClick={() => void onPublish(selected.id, !selected.is_published)}>{selected.is_published ? 'Снять с публикации' : 'Опубликовать место'}</button><button type="button" className="admin-secondary admin-danger" disabled={busy} onClick={() => { if (window.confirm(`Удалить место «${selected.name}»?`)) void onDelete(selected.id); }}>Удалить</button></>}</div>
    </form>
  );
}
