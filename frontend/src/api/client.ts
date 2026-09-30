import type {
  AdminCamera, AdminPlace, AdminSource, AdminUser, AuditEvent, CameraCheck, CameraInput,
  ImportInput, ImportPreview, ImportResult, LoginResponse, MapResponse,
  PlaceDetail, PlaceInput, SearchResponse, SourceInput,
} from '../types';
import routes from './routes.json';
import { sessionRejectedEvent } from '../admin/session';

type RouteName = keyof typeof routes;
function endpoint(name: RouteName, id?: number): string {
  return routes[name].path.replace(/\{[^}]+\}/, id === undefined ? '' : String(id));
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

async function request<T>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    if (response.status === 401 && token) {
      window.dispatchEvent(new CustomEvent(sessionRejectedEvent, { detail: token }));
    }
    const body = await response.json().catch(() => null) as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(response.status, body?.error?.code ?? 'http_error', body?.error?.message ?? `HTTP ${response.status}`);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

const json = (value: unknown) => JSON.stringify(value);

async function allPages<T>(path: string, token: string): Promise<T[]> {
  const items: T[] = [];
  for (let offset = 0; ; offset += 100) {
    const page = await request<T[]>(`${path}?limit=100&offset=${offset}`, {}, token);
    items.push(...page);
    if (page.length < 100) return items;
  }
}

export const publicApi = {
  map: (bbox: string, zoom: number, category?: string, includeOffline = false, signal?: AbortSignal) =>
    request<MapResponse>(`${endpoint('map')}?bbox=${encodeURIComponent(bbox)}&zoom=${zoom}${category ? `&category=${encodeURIComponent(category)}` : ''}${includeOffline ? '&include_offline=true' : ''}`, { signal }),
  search: (query: string, includeOffline = false, signal?: AbortSignal) =>
    request<SearchResponse>(`${endpoint('search')}?q=${encodeURIComponent(query)}&limit=10${includeOffline ? '&include_offline=true' : ''}`, { signal }),
  place: (id: number, signal?: AbortSignal) => request<PlaceDetail>(endpoint('place', id), { signal }),
};

export const adminApi = {
  login: (username: string, password: string) => request<LoginResponse>(endpoint('adminLogin'), {
    method: 'POST', body: json({ username, password }),
  }),
  me: (token: string) => request<AdminUser>(endpoint('adminMe'), {}, token),
  logout: (token: string) => request<void>(endpoint('adminLogout'), { method: 'POST' }, token),
  places: (token: string) => allPages<AdminPlace>(endpoint('adminPlaces'), token),
  sources: (token: string) => allPages<AdminSource>(endpoint('adminSources'), token),
  cameras: (token: string) => allPages<AdminCamera>(endpoint('adminCameras'), token),
  cameraChecks: (token: string, id: number, signal?: AbortSignal) =>
    request<CameraCheck[]>(`${endpoint('adminCameraChecks', id)}?limit=10`, { signal }, token),
  audit: (token: string) => allPages<AuditEvent>(endpoint('adminAudit'), token),
  createPlace: (token: string, body: PlaceInput) => request<AdminPlace>(endpoint('adminPlaces'), { method: 'POST', body: json(body) }, token),
  updatePlace: (token: string, id: number, body: Partial<PlaceInput> & { is_published?: boolean }) =>
    request<AdminPlace>(endpoint('adminPlace', id), { method: 'PATCH', body: json(body) }, token),
  deletePlace: (token: string, id: number) => request<void>(endpoint('adminPlace', id), { method: 'DELETE' }, token),
  createSource: (token: string, body: SourceInput) => request<AdminSource>(endpoint('adminSources'), { method: 'POST', body: json(body) }, token),
  updateSource: (token: string, id: number, body: Partial<SourceInput> & { is_approved?: boolean }) =>
    request<AdminSource>(endpoint('adminSource', id), { method: 'PATCH', body: json(body) }, token),
  deleteSource: (token: string, id: number) => request<void>(endpoint('adminSource', id), { method: 'DELETE' }, token),
  createCamera: (token: string, body: CameraInput) => request<AdminCamera>(endpoint('adminCameras'), { method: 'POST', body: json(body) }, token),
  updateCamera: (token: string, id: number, body: Partial<CameraInput> & { is_published?: boolean; status?: AdminCamera['status']; embed_verified_at?: string | null }) =>
    request<AdminCamera>(endpoint('adminCamera', id), { method: 'PATCH', body: json(body) }, token),
  deleteCamera: (token: string, id: number) => request<void>(endpoint('adminCamera', id), { method: 'DELETE' }, token),
  previewImport: (token: string, body: ImportInput) => request<ImportPreview>(endpoint('importPreview'), { method: 'POST', body: json(body) }, token),
  applyImport: (token: string, body: ImportInput) => request<ImportResult>(endpoint('importApply'), { method: 'POST', body: json(body) }, token),
};
