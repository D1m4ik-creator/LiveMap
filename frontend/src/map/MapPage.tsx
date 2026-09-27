import { useQuery } from '@tanstack/react-query';
import { ChevronDown, Compass, Layers3, List, LocateFixed, MapPin, Menu, Minus, Moon, Plus, Radio, Share2, Sun, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import type { Map as MapInstance } from 'maplibre-gl';
import { publicApi } from '../api/client';
import type { Coordinates } from '../types';
import { PlacePanel } from '../places/PlacePanel';
import { SearchBox, type SearchChoice } from '../places/SearchBox';
import { pluralRu } from '../ui/format';
import { prefersReducedMotion } from '../ui/motion';
import { SkeletonStack } from '../ui/SkeletonStack';
import { MapView, type MapFocus, type Viewport } from './MapView';
import { mapProvider } from './provider';

const categories = [
  { value: '', label: 'Все места' }, { value: 'bridge', label: 'Мосты' },
  { value: 'square', label: 'Площади' }, { value: 'street', label: 'Улицы' },
  { value: 'park', label: 'Парки' }, { value: 'station', label: 'Вокзалы' },
];

function validCoordinate(value: string | null, min: number, max: number): number | null {
  if (value === null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= min && parsed <= max ? parsed : null;
}

export function MapPage() {
  const navigate = useNavigate();
  const { placeId, city } = useParams();
  const [params, setParams] = useSearchParams();
  const selectedId = placeId && /^\d+$/.test(placeId) ? Number(placeId) : null;
  const cameraId = params.get('camera') && /^\d+$/.test(params.get('camera')!) ? Number(params.get('camera')) : null;
  const cityLng = validCoordinate(params.get('lng'), -180, 180);
  const cityLat = validCoordinate(params.get('lat'), -90, 90);
  const [theme, setTheme] = useState<'light' | 'dark'>(() => localStorage.getItem('livemap-theme') === 'dark' ? 'dark' : 'light');
  const [category, setCategory] = useState('');
  const [liveOnly, setLiveOnly] = useState(true);
  const [viewport, setViewport] = useState<Viewport | null>(null);
  const [stableViewport, setStableViewport] = useState<Viewport | null>(null);
  const [focus, setFocus] = useState<MapFocus | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const mapRef = useRef<MapInstance | null>(null);
  const onViewport = useCallback((next: Viewport) => setViewport(next), []);
  const onMapReady = useCallback((map: MapInstance | null) => { mapRef.current = map; }, []);

  useEffect(() => {
    if (!viewport) return;
    const timer = window.setTimeout(() => setStableViewport(viewport), 250);
    return () => window.clearTimeout(timer);
  }, [viewport]);
  useEffect(() => { localStorage.setItem('livemap-theme', theme); }, [theme]);
  useEffect(() => {
    const legacy = params.get('place');
    if (!placeId && legacy && /^\d+$/.test(legacy)) navigate(`/place/${legacy}`, { replace: true });
  }, [navigate, params, placeId]);
  const cityQuery = useQuery({
    queryKey: ['city-link', city], enabled: Boolean(city && (cityLng === null || cityLat === null)),
    queryFn: ({ signal }) => publicApi.search(city!, true, signal), staleTime: 60_000,
  });
  useEffect(() => {
    if (!city) return;
    const coordinates = cityLng !== null && cityLat !== null
      ? [cityLng, cityLat] as Coordinates
      : cityQuery.data?.suggestions.find((item) => item.kind === 'city' && item.label.split(',')[0].toLocaleLowerCase('ru-RU') === city.toLocaleLowerCase('ru-RU'))?.coordinates;
    if (coordinates) setFocus({ coordinates, zoom: 11, nonce: Date.now() });
  }, [city, cityLng, cityLat, cityQuery.data]);

  const mapQuery = useQuery({
    queryKey: ['map', stableViewport?.bbox, stableViewport?.zoom, category, liveOnly],
    enabled: Boolean(stableViewport), staleTime: 90_000, refetchInterval: 5 * 60_000,
    queryFn: ({ signal }) => publicApi.map(stableViewport!.bbox, stableViewport!.zoom, category, !liveOnly, signal),
    placeholderData: (previous) => previous,
  });
  const placeQuery = useQuery({
    queryKey: ['place', selectedId], enabled: selectedId !== null,
    queryFn: ({ signal }) => publicApi.place(selectedId!, signal), staleTime: 30_000,
  });
  useEffect(() => {
    if (placeQuery.data) setFocus({ coordinates: placeQuery.data.coordinates, zoom: 12, nonce: Date.now() });
  }, [placeQuery.data?.id]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (cameraId !== null) setParams({}, { replace: true });
      else if (selectedId !== null) navigate('/');
    };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [cameraId, selectedId, navigate, setParams]);

  const choose = (choice: SearchChoice) => {
    setFocus({ coordinates: choice.coordinates, zoom: choice.placeId ? 12 : 10, nonce: Date.now() });
    if (choice.placeId) navigate(`/place/${choice.placeId}`);
    else navigate(`/city/${encodeURIComponent(choice.label.split(',')[0])}?lng=${choice.coordinates[0]}&lat=${choice.coordinates[1]}`);
  };
  const share = async () => {
    try {
      if (navigator.share) await navigator.share({ title: 'LiveMap', url: window.location.href });
      else { await navigator.clipboard.writeText(window.location.href); setNotice('Ссылка скопирована'); }
    } catch { setNotice('Не удалось поделиться ссылкой'); }
    window.setTimeout(() => setNotice(null), 3500);
  };
  const locate = () => {
    navigator.geolocation?.getCurrentPosition(
      (position) => setFocus({ coordinates: [position.coords.longitude, position.coords.latitude], zoom: 11, nonce: Date.now() }),
      () => setNotice('Не удалось определить местоположение'),
      { timeout: 8000 },
    );
  };
  const visibleCount = mapQuery.data?.mode === 'points'
    ? mapQuery.data.points.reduce((sum, point) => sum + point.camera_count, 0)
    : mapQuery.data?.clusters.reduce((sum, cluster) => sum + cluster.camera_count, 0) ?? 0;

  return (
    <div className="map-app" data-theme={theme}>
      <MapView data={mapQuery.data} selectedId={selectedId} theme={theme} focus={focus} onViewport={onViewport}
        onSelect={(id) => navigate(`/place/${id}`)} onMapReady={onMapReady} />
      <header className="topbar">
        <Link to="/" className="brand-logo" aria-label="LiveMap — на главную"><span className="brand-symbol"><Radio size={20} /></span><span>LIVE<span>MAP</span></span></Link>
        <SearchBox onChoose={choose} includeOffline={!liveOnly} />
        <div className="topbar-actions">
          <span className="live-tag"><span className="live-pulse" /> СЕЙЧАС В ЭФИРЕ</span>
          <button className="icon-control desktop-only" title="Поделиться картой" aria-label="Поделиться картой" onClick={share}><Share2 size={19} /></button>
          <Link className="admin-link desktop-only" to="/admin">Панель управления</Link>
          <button className="icon-control mobile-only" aria-label="Открыть меню" onClick={() => setMenuOpen((value) => !value)}><Menu size={21} /></button>
        </div>
      </header>
      {menuOpen && <div className="mobile-menu"><Link to="/admin" onClick={() => setMenuOpen(false)}>Панель управления</Link><button onClick={() => { void share(); setMenuOpen(false); }}>Поделиться картой</button></div>}
      <div className="filterbar">
        <span className="filter-label"><Layers3 size={16} /> СЛОИ</span>
        <button className="filter-live" aria-pressed={liveOnly} onClick={() => setLiveOnly((value) => !value)}><span className="live-pulse" /> {liveOnly ? 'Только в эфире' : 'Все камеры'}</button>
        <div className="select-wrap"><select aria-label="Категория места" value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><ChevronDown size={15} /></div>
        {category && <button className="filter-clear" onClick={() => setCategory('')} aria-label="Сбросить категорию"><X size={15} /></button>}
      </div>
      <div className="map-controls" aria-label="Управление картой">
        <button aria-label="Увеличить масштаб" onClick={() => mapRef.current?.zoomIn()}><Plus size={21} /></button>
        <button aria-label="Уменьшить масштаб" onClick={() => mapRef.current?.zoomOut()}><Minus size={21} /></button>
        <span className="control-divider" />
        <button aria-label="Моё местоположение" onClick={locate}><LocateFixed size={20} /></button>
        <button aria-label={theme === 'light' ? 'Включить тёмную тему' : 'Включить светлую тему'} onClick={() => setTheme((value) => value === 'light' ? 'dark' : 'light')}>{theme === 'light' ? <Moon size={19} /> : <Sun size={19} />}</button>
        <span className="control-divider" />
        <button aria-label="Точки списком" aria-expanded={listOpen} aria-controls="visible-places" onClick={() => setListOpen((value) => !value)}><List size={20} /></button>
      </div>
      {listOpen && <section className="map-list-panel" id="visible-places" aria-label="Точки в видимой области">
        <div className="map-list-header"><strong>Точки в области карты</strong><button aria-label="Закрыть список точек" onClick={() => setListOpen(false)}><X size={17} /></button></div>
        {mapQuery.isPending && <p role="status">Загружаем точки…</p>}
        {mapQuery.data?.mode === 'points' && mapQuery.data.points.map((point) => <button key={point.id} onClick={() => { navigate(`/place/${point.id}`); setListOpen(false); }}>{point.name}, {point.city}<small>{point.online_count > 0 ? `${point.online_count} ${pluralRu(point.online_count, 'камера в эфире', 'камеры в эфире', 'камер в эфире')}` : 'Нет эфира'}</small></button>)}
        {mapQuery.data?.mode === 'clusters' && mapQuery.data.clusters.map((cluster) => <button key={cluster.id} aria-label={`Группа: ${cluster.place_count} ${pluralRu(cluster.place_count, 'место', 'места', 'мест')}, ${cluster.online_count > 0 ? `${cluster.online_count} в эфире` : 'нет эфира'}, координаты ${cluster.coordinates[1].toFixed(2)}, ${cluster.coordinates[0].toFixed(2)}. Приблизить карту`} onClick={() => { const map = mapRef.current; if (map) { const options = { center: cluster.coordinates, zoom: Math.min(map.getZoom() + 2, 10) }; if (prefersReducedMotion()) map.jumpTo(options); else map.easeTo(options); } setListOpen(false); }}>Группа: {cluster.place_count} {pluralRu(cluster.place_count, 'место', 'места', 'мест')}<small>{cluster.online_count > 0 ? `${cluster.online_count} в эфире` : 'Нет эфира'} · приблизить</small></button>)}
        {mapQuery.data && mapQuery.data.points.length + mapQuery.data.clusters.length === 0 && <p>Камер в этой области нет.</p>}
      </section>}
      {selectedId !== null ? (
        placeQuery.data ? <PlacePanel place={placeQuery.data} cameraId={cameraId} onCamera={(id) => setParams(id === null ? {} : { camera: String(id) }, { replace: true })} onClose={() => navigate('/')} onShare={() => void share()} />
          : <aside className="side-panel state-panel"><button className="back-button" onClick={() => navigate('/')}>← К карте</button>{placeQuery.isPending ? <SkeletonStack /> : <div role="alert"><strong>Не удалось открыть место</strong><p>{placeQuery.error instanceof Error ? placeQuery.error.message : 'Попробуйте ещё раз'}</p><button className="pill-button" onClick={() => void placeQuery.refetch()}>Повторить</button></div>}</aside>
      ) : (
        <aside className="side-panel welcome-panel">
          <div className="welcome-eyebrow"><Compass size={18} /> ИССЛЕДУЙТЕ ГОРОДА</div>
          <h1>Мир рядом.<br /><em>Посмотрите сейчас.</em></h1>
          <p>Выберите точку на карте и загляните в город через публичные камеры с проверенными источниками.</p>
          <div className="welcome-divider" />
          <div className="map-stat" role="status"><span className="stat-number">{mapQuery.isPending ? '—' : String(visibleCount).padStart(2, '0')}</span><span>{pluralRu(visibleCount, 'камера', 'камеры', 'камер')} в видимой<br />области карты</span><span className="stat-icon"><Radio size={24} /></span></div>
          <div className="welcome-tip"><MapPin size={17} /><span>Приближайте карту, чтобы увидеть места и камеры.</span></div>
          <div className="welcome-source">Подложка: {mapProvider.name}. Источники видео указаны в карточках камер.</div>
        </aside>
      )}
      {mapQuery.isError && <div className="map-toast" role="alert">Не удалось загрузить камеры. <button onClick={() => void mapQuery.refetch()}>Повторить</button></div>}
      {city && cityQuery.isError && <div className="map-toast" role="alert">Не удалось найти город. <button onClick={() => void cityQuery.refetch()}>Повторить</button></div>}
      {city && cityQuery.data && cityLng === null && cityLat === null && !cityQuery.data.suggestions.some((item) => item.kind === 'city' && item.label.split(',')[0].toLocaleLowerCase('ru-RU') === city.toLocaleLowerCase('ru-RU')) && <div className="map-toast" role="status">Город не найден в каталоге камер.</div>}
      {mapQuery.data?.truncated && <div className="map-toast" role="status">Слишком много точек. Приблизьте карту.</div>}
      {notice && <div className="map-toast" role="status">{notice}</div>}
      <div className="map-watermark">LIVEMAP <span>·</span> {mapProvider.name}</div>
    </div>
  );
}
