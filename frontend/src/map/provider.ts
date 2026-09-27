export const maptilerApiKey = import.meta.env.VITE_MAPTILER_KEY?.trim();
const customStyle = import.meta.env.VITE_MAP_STYLE_URL?.trim();

export const mapProvider = {
  name: customStyle?.includes('maptiler.com') ? 'MapTiler' : customStyle ? 'Пользовательский стиль' : 'OpenFreeMap',
  hasGeocoder: Boolean(maptilerApiKey),
  lightStyle: customStyle || 'https://tiles.openfreemap.org/styles/positron',
  darkStyle: customStyle || 'https://tiles.openfreemap.org/styles/dark',
};

export type GeocodeResult = { label: string; coordinates: [number, number] };

export async function geocode(query: string, signal?: AbortSignal): Promise<GeocodeResult[]> {
  if (!maptilerApiKey) return [];
  const url = new URL(`https://api.maptiler.com/geocoding/${encodeURIComponent(query)}.json`);
  url.searchParams.set('key', maptilerApiKey);
  url.searchParams.set('language', 'ru');
  url.searchParams.set('country', 'ru');
  url.searchParams.set('limit', '5');
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error('Поиск адресов временно недоступен');
  const data = await response.json() as { features?: { place_name?: string; center?: [number, number] }[] };
  return (data.features ?? []).filter((item) => item.place_name && item.center)
    .map((item) => ({ label: item.place_name!, coordinates: item.center! }));
}
