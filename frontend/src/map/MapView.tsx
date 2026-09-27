import { useEffect, useRef, useState } from 'react';
import * as maplibregl from 'maplibre-gl';
import type { GeoJSONSource, Map as MapInstance } from 'maplibre-gl';
import type { FeatureCollection, Point } from 'geojson';
import type { Coordinates, MapResponse } from '../types';
import { mapProvider } from './provider';
import { prefersReducedMotion } from '../ui/motion';
import 'maplibre-gl/dist/maplibre-gl.css';

export type Viewport = { bbox: string; zoom: number };
export type MapFocus = { coordinates: Coordinates; zoom: number; nonce: number };

type Props = {
  data?: MapResponse; selectedId: number | null; theme: 'light' | 'dark';
  focus: MapFocus | null; onViewport: (viewport: Viewport) => void;
  onSelect: (id: number) => void; onMapReady?: (map: MapInstance | null) => void;
};

function wrapLongitude(value: number): number {
  return ((value + 180) % 360 + 360) % 360 - 180;
}

function currentViewport(map: MapInstance): Viewport {
  const bounds = map.getBounds();
  const spansWorld = bounds.getEast() - bounds.getWest() >= 359.999;
  const west = spansWorld ? -180 : wrapLongitude(bounds.getWest());
  const east = spansWorld ? 180 : wrapLongitude(bounds.getEast());
  const south = Math.max(-89.999, bounds.getSouth());
  const north = Math.min(89.999, bounds.getNorth());
  return {
    bbox: [west, south, east, north].map((n) => n.toFixed(3)).join(','),
    zoom: Math.round(map.getZoom()),
  };
}

function fitRussia(map: MapInstance) {
  const mobile = window.innerWidth <= 760;
  const mobileLandscape = mobile && window.innerHeight <= 560;
  const padding = mobileLandscape
    ? { top: 90, bottom: 15, left: 300, right: 70 }
    : mobile
      ? { top: 135, bottom: 10, left: 18, right: 18 }
      : { top: 155, bottom: 38, left: 445, right: 66 };
  map.fitBounds([[19, 41], [180, 82]], { padding, maxZoom: 3, duration: 0 });
}

function features(data?: MapResponse): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: [
      ...(data?.points ?? []).map((item) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: item.coordinates },
        properties: { kind: 'point', id: item.id, count: item.camera_count, name: item.name, status: item.status },
      })),
      ...(data?.clusters ?? []).map((item) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: item.coordinates },
        properties: { kind: 'cluster', id: item.id, count: item.camera_count, name: `${item.place_count} мест`, status: item.status },
      })),
    ],
  };
}

function installLayers(map: MapInstance) {
  if (map.getSource('live-places')) return;
  map.addSource('live-places', { type: 'geojson', data: features() });
  map.addLayer({
    id: 'live-halo', source: 'live-places', type: 'circle',
    paint: {
      'circle-radius': ['case', ['==', ['get', 'kind'], 'cluster'], 23, 18],
      'circle-color': ['case', ['==', ['get', 'status'], 'online'], 'rgba(0,169,157,.18)', 'rgba(92,111,118,.2)'], 'circle-blur': 0.1,
    },
  });
  map.addLayer({
    id: 'live-marker', source: 'live-places', type: 'circle',
    paint: {
      'circle-radius': ['case', ['==', ['get', 'kind'], 'cluster'], 18, 14],
      'circle-color': ['case', ['==', ['get', 'status'], 'online'], '#00A99D', '#5C6F76'], 'circle-stroke-width': 3,
      'circle-stroke-color': '#fff',
    },
  });
  map.addLayer({
    id: 'live-selected', source: 'live-places', type: 'circle',
    filter: ['==', ['get', 'id'], -1],
    paint: { 'circle-radius': 20, 'circle-color': 'rgba(255,107,87,.2)', 'circle-stroke-color': '#FF6B57', 'circle-stroke-width': 3 },
  });
  map.addLayer({
    id: 'live-count', source: 'live-places', type: 'symbol',
    layout: { 'text-field': ['to-string', ['get', 'count']], 'text-size': 12, 'text-font': ['Noto Sans Bold'] },
    paint: { 'text-color': ['case', ['==', ['get', 'status'], 'online'], '#123039', '#ffffff'] },
  });
}

export function MapView({ data, selectedId, theme, focus, onViewport, onSelect, onMapReady }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapInstance | null>(null);
  const styleThemeRef = useRef<'light' | 'dark'>('light');
  const dataRef = useRef(data);
  const selectedRef = useRef(selectedId);
  const viewportRef = useRef(onViewport);
  const selectRef = useRef(onSelect);
  const readyRef = useRef(onMapReady);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  dataRef.current = data;
  selectedRef.current = selectedId;
  viewportRef.current = onViewport;
  selectRef.current = onSelect;
  readyRef.current = onMapReady;

  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: mapProvider.lightStyle,
      center: [90, 60], zoom: 0, minZoom: 0, maxZoom: 18,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    readyRef.current?.(map);
    let initialPositionSet = false;
    map.on('style.load', () => {
      if (!initialPositionSet) {
        initialPositionSet = true;
        fitRussia(map);
      }
      installLayers(map);
      (map.getSource('live-places') as GeoJSONSource).setData(features(dataRef.current));
      map.setFilter('live-selected', ['==', ['get', 'id'], selectedRef.current ?? -1]);
      setLoaded(true);
      setError(null);
      viewportRef.current(currentViewport(map));
    });
    const onResize = () => {
      map.resize();
      if (map.getZoom() <= 3 && selectedRef.current === null) fitRussia(map);
      viewportRef.current(currentViewport(map));
    };
    window.addEventListener('resize', onResize);
    map.on('moveend', () => viewportRef.current(currentViewport(map)));
    map.on('click', 'live-marker', (event) => {
      const feature = event.features?.[0];
      if (!feature || feature.geometry.type !== 'Point') return;
      const center = feature.geometry.coordinates as Coordinates;
      if (feature.properties?.kind === 'cluster') {
        const options = { center, zoom: Math.min(map.getZoom() + 2, 10) };
        if (prefersReducedMotion()) map.jumpTo(options);
        else map.easeTo({ ...options, duration: 500 });
      } else if (typeof feature.properties?.id === 'number') {
        selectRef.current(feature.properties.id);
      }
    });
    map.on('mouseenter', 'live-marker', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'live-marker', () => { map.getCanvas().style.cursor = ''; });
    map.on('error', (event) => {
      if (!map.isStyleLoaded()) setError(event.error?.message || 'Не удалось загрузить карту');
    });
    return () => { window.removeEventListener('resize', onResize); readyRef.current?.(null); mapRef.current = null; map.remove(); };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource('live-places')) return;
    (map.getSource('live-places') as GeoJSONSource).setData(features(data));
  }, [data]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer('live-selected')) map.setFilter('live-selected', ['==', ['get', 'id'], selectedId ?? -1]);
  }, [selectedId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || styleThemeRef.current === theme) return;
    styleThemeRef.current = theme;
    const style = theme === 'dark' ? mapProvider.darkStyle : mapProvider.lightStyle;
    setLoaded(false);
    map.setStyle(style);
  }, [theme]);

  useEffect(() => {
    if (!focus || !mapRef.current) return;
    if (prefersReducedMotion()) mapRef.current.jumpTo({ center: focus.coordinates, zoom: focus.zoom });
    else mapRef.current.flyTo({ center: focus.coordinates, zoom: focus.zoom, speed: 1.2 });
  }, [focus]);

  return (
    <div className="map-frame">
      <div className="map-canvas" ref={container} role="application" aria-label="Интерактивная карта России с камерами" aria-describedby="map-accessibility-help" />
      <p className="sr-only" id="map-accessibility-help">Для выбора точки с клавиатуры используйте кнопку «Точки списком».</p>
      {!loaded && !error && <div className="map-loading" role="status">Загружаем карту России…</div>}
      {error && <div className="map-error" role="alert"><strong>Карта недоступна</strong><span>{error}</span><button onClick={() => { setError(null); mapRef.current?.setStyle(theme === 'dark' ? mapProvider.darkStyle : mapProvider.lightStyle); }}>Повторить</button></div>}
    </div>
  );
}
