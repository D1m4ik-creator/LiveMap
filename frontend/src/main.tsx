import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CameraPlayer } from './CameraPlayer';
import type { PlaceDetail, PublicCamera } from './types';
import './style.css';

function App() {
  const placeId = new URLSearchParams(window.location.search).get('place');
  const [place, setPlace] = useState<PlaceDetail | null>(null);
  const [camera, setCamera] = useState<PublicCamera | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!placeId || !/^\d+$/.test(placeId)) return;
    const controller = new AbortController();
    fetch(`/api/v1/places/${placeId}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error('Место не найдено'); return response.json() as Promise<PlaceDetail>; })
      .then(setPlace)
      .catch((error: unknown) => { if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : 'Не удалось загрузить место'); });
    return () => controller.abort();
  }, [placeId]);

  return (
    <main className="page">
      <div className="brand"><span className="brand-mark">L</span><span>LIVE<span className="brand-accent">MAP</span></span><span className="brand-caption">Камеры России</span></div>
      <div className="layout">
        <section className="intro"><span className="eyebrow">01 / ПРЯМО СЕЙЧАС</span><h1>Место ближе,<br /><em>чем кажется.</em></h1><p>Выберите камеру, чтобы увидеть город таким, какой он сейчас. Источники публикуются после проверки прав и доступности.</p><div className="orb" aria-hidden="true" /></section>
        <section className="camera-list" aria-label="Камеры места">
          <div className="list-top"><span>ТОЧКА НА КАРТЕ</span><span>{place?.city ?? 'РОССИЯ'}</span></div>
          <h2>{place?.name ?? 'Прямые трансляции'}</h2>
          <p className="list-subtitle">{place?.address ?? 'Откройте страницу с параметром ?place=ID, чтобы посмотреть камеры опубликованного места.'}</p>
          {message && <p className="notice">{message}</p>}
          {place?.cameras.map((item) => (
            <button className="camera-row" key={item.id} onClick={() => setCamera(item)}>
              <span className={`signal-dot ${item.status}`} /><span className="camera-name">{item.name}<small>{item.source_name}</small></span><span className="camera-status">{item.status === 'online' ? 'Смотреть' : item.availability_note ?? item.status}</span><span className="arrow">↗</span>
            </button>
          ))}
          <div className="list-bottom">{place ? `${place.cameras.length} камер` : 'КАТАЛОГ В РАЗРАБОТКЕ'} <span>● LIVE MAP</span></div>
        </section>
      </div>
      {camera && <div className="modal-backdrop" onClick={() => setCamera(null)}><div onClick={(event) => event.stopPropagation()}><CameraPlayer camera={camera} onClose={() => setCamera(null)} /></div></div>}
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
