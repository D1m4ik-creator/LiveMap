import Hls from 'hls.js';
import { Maximize2, Volume2, VolumeX } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { PublicCamera } from '../types';

type Props = { camera: PublicCamera; onClose: () => void; preview?: boolean };
type PlayerState = 'loading' | 'playing' | 'no-signal' | 'error';

function safePlayback(camera: PublicCamera, preview: boolean): URL | null {
  if ((!preview && camera.status !== 'online') || !camera.playback_url) return null;
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

export function CameraPlayer({ camera, onClose, preview = false }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const [state, setState] = useState<PlayerState>('loading');
  const [attempt, setAttempt] = useState(0);
  const [muted, setMuted] = useState(true);
  const [live, setLive] = useState<boolean | null>(null);
  const url = useMemo(() => safePlayback(camera, preview), [camera, preview]);

  useEffect(() => {
    setState('loading');
    setLive(null);
    if (!url || camera.playback_type !== 'hls') return;
    const video = videoRef.current;
    if (!video) return;

    let hls: Hls | null = null;
    let retries = 0;
    let lastProgress = Date.now();
    let lastTime = -1;
    let isLive = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    const playable = () => { lastProgress = Date.now(); setState('playing'); };
    const failed = () => setState('error');
    video.addEventListener('playing', playable);
    video.addEventListener('error', failed);

    if (Hls.isSupported()) {
      hls = new Hls({ enableWorker: true, lowLatencyMode: true, startPosition: -1,
        liveSyncDurationCount: 2, liveMaxLatencyDurationCount: 5, maxLiveSyncPlaybackRate: 1.2 });
      hlsRef.current = hls;
      hls.on(Hls.Events.LEVEL_LOADED, (_event, data) => {
        isLive = data.details.live;
        setLive(data.details.live);
        if (!data.details.live) {
          video.pause();
          hls?.stopLoad();
          setState('no-signal');
        }
      });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data.fatal) return;
        setState(data.type === Hls.ErrorTypes.NETWORK_ERROR ? 'no-signal' : 'error');
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR && retries < 3) {
          retryTimer = setTimeout(() => hls?.startLoad(-1), 1000 * 2 ** retries++);
        }
      });
      hls.loadSource(url.href);
      hls.attachMedia(video);
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url.href;
    } else {
      failed();
    }
    const reconnect = () => {
      if (!hls || !isLive || retries >= 3) {
        setState('no-signal');
        return;
      }
      retries++;
      lastProgress = Date.now();
      setState('loading');
      hls.startLoad(-1);
      const position = hls.liveSyncPosition;
      if (position != null && video.seekable.length && position <= video.seekable.end(video.seekable.length - 1)) {
        video.currentTime = position;
      }
      // This path follows a playing stream or ended live buffer, never a user pause.
      void video.play().catch(() => setState('no-signal'));
    };
    const ended = () => { if (isLive) reconnect(); else setState('no-signal'); };
    video.addEventListener('ended', ended);
    const watchdog = setInterval(() => {
      if (video.paused || !isLive) return;
      if (Math.abs(video.currentTime - lastTime) > 0.05) {
        lastTime = video.currentTime;
        lastProgress = Date.now();
      } else if (Date.now() - lastProgress > 15_000) {
        reconnect();
      }
    }, 3000);

    return () => {
      video.removeEventListener('playing', playable);
      video.removeEventListener('error', failed);
      video.removeEventListener('ended', ended);
      clearTimeout(retryTimer);
      clearInterval(watchdog);
      hlsRef.current = null;
      hls?.destroy();
      video.pause();
      video.removeAttribute('src');
      video.load();
    };
  }, [camera.id, camera.playback_type, url, attempt]);

  const goLive = () => {
    const video = videoRef.current;
    if (!video) return;
    const position = hlsRef.current?.liveSyncPosition;
    if (position != null) video.currentTime = position;
    else if (video.seekable.length) video.currentTime = Math.max(video.seekable.start(0), video.seekable.end(video.seekable.length - 1) - 2);
    void video.play().catch(() => setState('error'));
  };

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
            {(state === 'no-signal' || state === 'error') && <div className="player-overlay" role="alert">{live === false ? 'Источник передаёт запись вместо прямого эфира.' : state === 'no-signal' ? 'Нет сигнала.' : 'Ошибка воспроизведения.'} <button onClick={() => setAttempt((value) => value + 1)}>Повторить</button></div>}
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
        {playable && camera.playback_type === 'hls' && live !== false && <div>
          <button className="player-live-button" onClick={goLive} disabled={state !== 'playing'}>К прямому эфиру</button>
          <span>{state === 'playing' ? ' Прямой эфир · шкала показывает обновляемый буфер' : ' Подключение к эфиру'}</span>
        </div>}
        <div><span className={`signal-dot ${camera.status}`} />{preview ? 'Предпросмотр черновика · камера ещё не опубликована' : camera.status === 'online' ? 'Последняя проверка: доступна' : unavailableText}</div>
        <a href={camera.source_page_url} target="_blank" rel="noopener noreferrer">Источник: {camera.attribution} ↗</a>
      </footer>
    </div>
  );
}
