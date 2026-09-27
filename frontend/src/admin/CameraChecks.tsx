import { useQuery } from '@tanstack/react-query';
import { adminApi } from '../api/client';
import { StatusBadge } from '../ui/StatusBadge';
import { ActionButton } from '../ui/ActionButton';

export function CameraChecks({ token, cameraId }: { token: string; cameraId: number }) {
  const checks = useQuery({
    queryKey: ['admin', 'checks', cameraId],
    queryFn: ({ signal }) => adminApi.cameraChecks(token, cameraId, signal),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  return <section className="camera-checks" aria-label="История проверок камеры">
    <div className="camera-checks-head"><h3>История проверок</h3><ActionButton disabled={checks.isFetching} onClick={() => void checks.refetch()}>Обновить</ActionButton></div>
    {checks.isPending && <p role="status">Загружаем проверки…</p>}
    {checks.isError && <p role="alert">Не удалось загрузить проверки. Повторите запрос.</p>}
    {checks.data?.length === 0 && <p>Проверок пока нет.</p>}
    {checks.data?.map((check) => <div className="camera-check-row" key={check.id}>
      <time dateTime={check.checked_at}>{new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(check.checked_at))}</time>
      <StatusBadge status={check.result} />
      <span>{check.code}</span>
    </div>)}
  </section>;
}
