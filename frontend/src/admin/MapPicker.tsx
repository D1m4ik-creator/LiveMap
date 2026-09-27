import { useEffect, useRef } from 'react';
import * as maplibregl from 'maplibre-gl';
import type { Coordinates } from '../types';
import { mapProvider } from '../map/provider';
import { prefersReducedMotion } from '../ui/motion';

export function MapPicker({ coordinates, onChange }: { coordinates: Coordinates; onChange: (value: Coordinates) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const changeRef = useRef(onChange);
  changeRef.current = onChange;
  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current, style: mapProvider.lightStyle,
      center: coordinates, zoom: 10, attributionControl: { compact: true },
    });
    const marker = new maplibregl.Marker({ color: '#00A99D' }).setLngLat(coordinates).addTo(map);
    mapRef.current = map;
    markerRef.current = marker;
    map.on('click', (event) => changeRef.current([Number(event.lngLat.lng.toFixed(6)), Number(event.lngLat.lat.toFixed(6))]));
    return () => { mapRef.current = null; markerRef.current = null; map.remove(); };
  }, []);
  useEffect(() => {
    markerRef.current?.setLngLat(coordinates);
    if (mapRef.current && !mapRef.current.getBounds().contains(coordinates)) {
      if (prefersReducedMotion()) mapRef.current.jumpTo({ center: coordinates, zoom: 10 });
      else mapRef.current.flyTo({ center: coordinates, zoom: 10, speed: 1.4 });
    }
  }, [coordinates]);
  return <div className="admin-map-picker"><div ref={container} role="application" aria-label="Выбор координат места" /></div>;
}
