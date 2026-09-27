import type { CameraStatus } from '../types';

const statusText: Record<CameraStatus, string> = {
  online: 'В эфире', offline: 'Недоступна', unknown: 'Проверяем',
};

export function StatusBadge({ status }: { status: CameraStatus }) {
  return <span className={`status-badge ${status}`}><span aria-hidden="true" />{statusText[status]}</span>;
}
