import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { setWorkerUrl } from 'maplibre-gl';
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { lazy, StrictMode, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router';
import { MapPage } from './map/MapPage';
import './style.css';

// Bundle the worker and its shared imports into a same-origin asset for CSP.
setWorkerUrl(mapWorkerUrl);

const AdminPage = lazy(() => import('./admin/AdminPage').then(({ AdminPage }) => ({ default: AdminPage })));

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

createRoot(document.getElementById('root')!).render(
  <StrictMode><QueryClientProvider client={queryClient}><BrowserRouter><Suspense fallback={<div className="route-loading" role="status">Загружаем LiveMap…</div>}><Routes>
    <Route path="/" element={<MapPage />} />
    <Route path="/place/:placeId" element={<MapPage />} />
    <Route path="/city/:city" element={<MapPage />} />
    <Route path="/admin" element={<AdminPage />} />
    <Route path="*" element={<MapPage />} />
  </Routes></Suspense></BrowserRouter></QueryClientProvider></StrictMode>,
);
