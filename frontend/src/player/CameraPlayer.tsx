import Hls from 'hls.js';
import { Maximize2, Volume2, VolumeX } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { PublicCamera } from '../types';

type Props = { camera: PublicCamera; onClose: () => void };
type PlayerState = 'loading' | 'playing' | 'no-signal' | 'error';

function safePlayback(camera: PublicCamera): URL | null {
  if (camera.status !== 'online' || !camera.playback_url) return null;
  try {
    const url = new URL(camera.playback_url);
    if (url.protocol !== 'https:' || url.username || url.password) return null;
    if (camera.playback_type !== 'iframe' && url.search) return null;
    if (camera.playback_type === 'iframe' && url.hostname !== camera.embed_host) return null;
    return url;
  } catch {
    return null;
  }
}

export function CameraPlayer({ camera, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<PlayerState>('loading');
  const [attempt, setAttempt] = useState(0);
  const [muted, setMuted] = useState(true);
  const url = useMemo(() => safePlayback(camera), [camera]);

  useEffect(() => {
    setState('loading');
    if (!url || camera.playback_type !== 'hls') return;
    const video = videoRef.current;
    if (!video) return;

    let hls: Hls | null = null;
    const playable = () => setState('playing');
    const failed = () => setState('error');
    video.addEventListener('playing', playable);
    video.addEventListener('error', failed);

    if (Hls.isSupported()) {
      hls = new Hls({ enableWorker: true, lowLatencyMode: true });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal) setState(data.type === Hls.ErrorTypes.NETWORK_ERROR ? 'no-signal' : 'error');
      });
      hls.loadSource(url.href);
      hls.attachMedia(video);
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url.href;
    } else {
      failed();
    }

    return () => {
      video.removeEventListener('playing', playable);
      video.removeEventListener('error', failed);
      hls?.destroy();
      video.pause();
      video.removeAttribute('src');
      video.load();
    };
  }, [camera.id, camera.playback_type, url, attempt]);

  const playable = Boolean(url && (camera.playback_type === 'hls' || camera.playback_type === 'iframe'));
  const unavailableText = camera.availability_note ?? 'Для этой камеры нет доступной трансляции.';

  return (
    <div className="player-shell" aria-label={`Камера ${camera.name}`}>
      <header className="player-header">
        <div><span className="eyebrow">LIVE / КАМЕРА {String(camera.id).padStart(3, '0')}</span><h2>{camera.name}</h2></div>
        <div className="player-actions">
          {playable && camera.playback_type === 'hls' && <button onClick={() => setMuted((value) => !value)} aria-label={muted ? 'Включить звук' : 'Выключить звук'}>{muted ? <VolumeX size={16} /> : <Volume2 size={16} />}</button>}
          <button disabled={!playable} onClick={() => void stageRef.current?.requestFullscreen()} aria-label="Во весь экран"><Maximize2 size={15} /></button>
          <button className="icon-button" onClick={onClose} aria-label="Закрыть трансляцию">×</button>
        </div>
      </header>
      <div className="player-stage" ref={stageRef}>
        {!playable && <div className="player-message" role="status"><span className="signal-dot muted" />{unavailableText}</div>}
        {playable && camera.playback_type === 'hls' && (
          <>
            <video ref={videoRef} controls autoPlay muted={muted} playsInline aria-label={camera.name} />
            {state === 'loading' && <div className="player-overlay" role="status">Подключаемся к трансляции…</div>}
            {(state === 'no-signal' || state === 'error') && <div className="player-overlay" role="alert">{state === 'no-signal' ? 'Нет сигнала.' : 'Ошибка воспроизведения.'} <button onClick={() => setAttempt((value) => value + 1)}>Повторить</button></div>}
          </>
        )}
        {playable && camera.playback_type === 'iframe' && (
          <iframe
            key={`${camera.id}-${attempt}`}
            src={url!.href}
            title={camera.name}
            sandbox="allow-scripts allow-same-origin allow-presentation"
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            referrerPolicy="strict-origin-when-cross-origin"
            onLoad={() => setState('playing')}
            onError={() => setState('error')}
          />
        )}
        {playable && camera.playback_type === 'iframe' && state === 'error' && <div className="player-overlay" role="alert">Не удалось открыть встраиваемый плеер. <button onClick={() => setAttempt((value) => value + 1)}>Повторить</button></div>}
      </div>
      <footer className="player-footer">
        <div><span className={`signal-dot ${camera.status}`} />{camera.status === 'online' ? 'Последняя проверка: доступна' : unavailableText}</div>
        <a href={camera.source_page_url} target="_blank" rel="noopener noreferrer">Источник: {camera.attribution} ↗</a>
      </footer>
    </div>
  );
}
