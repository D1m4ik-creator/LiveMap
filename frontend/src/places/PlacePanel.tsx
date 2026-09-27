import { ArrowLeft, ExternalLink, MapPin, Radio, Share2 } from 'lucide-react';
import { lazy, Suspense, useEffect, useRef } from 'react';
import type { PlaceDetail } from '../types';
import { CameraCard } from '../cameras/CameraCard';

const CameraPlayer = lazy(() => import('../player/CameraPlayer').then(({ CameraPlayer }) => ({ default: CameraPlayer })));

export function PlacePanel({ place, cameraId, onCamera, onClose, onShare }: {
  place: PlaceDetail; cameraId: number | null; onCamera: (id: number | null) => void;
  onClose: () => void; onShare: () => void;
}) {
  const camera = place.cameras.find((item) => item.id === cameraId);
  const hasLiveCamera = place.cameras.some((item) => item.status === 'online' && item.playback_url);
  const playerRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { headingRef.current?.focus(); }, [place.id]);
  useEffect(() => {
    if (cameraId !== null && playerRef.current) {
      playerRef.current.scrollIntoView({ block: 'nearest', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    }
  }, [cameraId]);
  return (
    <section className="place-panel" aria-label={`Место ${place.name}`}>
      <div className="panel-scroll">
        <div className="panel-topline"><button className="back-button" onClick={onClose}><ArrowLeft size={17} /> Назад к карте</button><button className="icon-plain" onClick={onShare} aria-label="Поделиться местом"><Share2 size={18} /></button></div>
        <div className="panel-hero">
          <div className="panel-kicker"><span className="live-pulse" /> ТОЧКА НА КАРТЕ <span className="separator">/</span> {place.city.toUpperCase()}</div>
          <h1 ref={headingRef} tabIndex={-1}>{place.name}</h1>
          <p><MapPin size={16} /> {place.address || `${place.city}, ${place.region}`}</p>
          <div className="coordinates">{place.coordinates[1].toFixed(4)}° N&nbsp;&nbsp; {place.coordinates[0].toFixed(4)}° E</div>
        </div>
        <div className="panel-section-title"><span>КАМЕРЫ РЯДОМ</span><span>{String(place.cameras.length).padStart(2, '0')}</span></div>
        <div className="camera-cards">
          {place.cameras.map((item) => <CameraCard key={item.id} camera={item} selected={item.id === cameraId} onClick={() => onCamera(item.id)} />)}
        </div>
        {camera && <div className="embedded-player" ref={playerRef}><Suspense fallback={<div className="player-loading" role="status">Загружаем плеер…</div>}><CameraPlayer key={camera.id} camera={camera} onClose={() => onCamera(null)} /></Suspense></div>}
        {!camera && <div className="camera-prompt"><span className="prompt-orbit"><Radio size={24} /></span><strong>{hasLiveCamera ? 'Взгляните на место прямо сейчас' : 'Трансляции сейчас недоступны'}</strong><span>{hasLiveCamera ? 'Выберите камеру, чтобы открыть трансляцию.' : 'Выберите камеру, чтобы узнать её состояние и открыть страницу источника.'}</span></div>}
        <div className="panel-footnote"><ExternalLink size={14} /> Видео предоставляют владельцы публичных источников. Доступность может измениться в любой момент.</div>
      </div>
    </section>
  );
}
