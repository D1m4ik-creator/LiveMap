import { Clock3, Radio, VideoOff } from 'lucide-react';
import type { PublicCamera } from '../types';
import { StatusBadge } from '../ui/StatusBadge';

function checkedAt(value: string | null): string {
  if (!value) return 'Проверка ещё не проводилась';
  return `Проверено ${new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))}`;
}

export function CameraCard({ camera, selected, onClick }: {
  camera: PublicCamera; selected: boolean; onClick: () => void;
}) {
  return <button className={`camera-card ${selected ? 'selected' : ''}`} onClick={onClick}>
    <span className="camera-card-icon">{camera.status === 'online' ? <Radio size={21} /> : <VideoOff size={21} />}</span>
    <span className="camera-card-main"><strong>{camera.name}</strong><small>{camera.source_name}</small><span className="camera-meta"><Clock3 size={13} /> {checkedAt(camera.last_checked_at)}</span></span>
    <StatusBadge status={camera.status} />
  </button>;
}
