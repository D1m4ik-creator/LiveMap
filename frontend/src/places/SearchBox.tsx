import { useQuery } from '@tanstack/react-query';
import { MapPin, Search, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { publicApi } from '../api/client';
import type { Coordinates, SearchSuggestion } from '../types';
import { geocode, mapProvider } from '../map/provider';

export type SearchChoice = { label: string; coordinates: Coordinates; placeId: number | null };

export function SearchBox({ onChoose, includeOffline }: { onChoose: (choice: SearchChoice) => void; includeOffline: boolean }) {
  const [value, setValue] = useState('');
  const [term, setTerm] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  useEffect(() => {
    const timer = window.setTimeout(() => setTerm(value.trim()), 350);
    return () => window.clearTimeout(timer);
  }, [value]);
  const local = useQuery({
    queryKey: ['search', term, includeOffline], enabled: term.length >= 2,
    queryFn: ({ signal }) => publicApi.search(term, includeOffline, signal), staleTime: 30_000,
  });
  const external = useQuery({
    queryKey: ['geocode', term], enabled: term.length >= 3 && mapProvider.hasGeocoder,
    queryFn: ({ signal }) => geocode(term, signal), staleTime: 5 * 60_000,
  });
  const waitingForTerm = value.trim() !== term;
  const suggestions: (SearchSuggestion & { external?: boolean })[] = waitingForTerm ? [] : [
    ...(local.data?.suggestions ?? []),
    ...(external.data ?? []).filter((item) => !(local.data?.suggestions ?? []).some((own) => own.label === item.label))
      .map((item) => ({ kind: 'address' as const, label: item.label, coordinates: item.coordinates, place_id: null, external: true })),
  ].slice(0, 10);
  const choose = (item: SearchSuggestion) => {
    onChoose({ label: item.label, coordinates: item.coordinates, placeId: item.place_id });
    setValue(item.label);
    setOpen(false);
  };

  return (
    <div className="search-wrap">
      <div className="search-field">
        <Search size={19} aria-hidden="true" />
        <input
          aria-label="Поиск города, улицы или места" aria-expanded={open && value.length >= 2}
          aria-controls="search-results" aria-activedescendant={open && suggestions[active] ? `search-option-${active}` : undefined}
          role="combobox" aria-autocomplete="list"
          placeholder="Город, улица или место"
          value={value} onChange={(event) => { setValue(event.target.value); setOpen(true); setActive(0); }}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setOpen(false);
            if (event.key === 'ArrowDown') { event.preventDefault(); setActive((index) => Math.max(0, Math.min(index + 1, suggestions.length - 1))); }
            if (event.key === 'ArrowUp') { event.preventDefault(); setActive((index) => Math.max(0, index - 1)); }
            if (event.key === 'Enter' && suggestions[active]) choose(suggestions[active]);
          }}
        />
        {value && <button className="icon-plain" aria-label="Очистить поиск" onClick={() => { setValue(''); setOpen(false); }}><X size={17} /></button>}
      </div>
      {open && value.trim().length >= 2 && (
        <div className="search-results" id="search-results" role="listbox">
          {(waitingForTerm || local.isPending || external.isFetching) && <div className="search-hint">Ищем места…</div>}
          {local.isError && <div className="search-hint error">Каталог временно недоступен</div>}
          {suggestions.map((item, index) => (
            <button key={`${item.label}-${index}`} id={`search-option-${index}`} role="option" aria-selected={active === index} className={active === index ? 'active' : ''}
              onMouseDown={(event) => event.preventDefault()} onClick={() => choose(item)}>
              <MapPin size={17} aria-hidden="true" /><span>{item.label}<small>{item.place_id ? 'Камера в каталоге' : item.external ? 'Адрес на карте' : 'Город в каталоге'}</small></span>
            </button>
          ))}
          {!waitingForTerm && !local.isPending && !local.isFetching && !external.isFetching && suggestions.length === 0 && !local.isError && (
            <div className="search-hint">Ничего не найдено{!mapProvider.hasGeocoder ? '. Поиск других адресов появится после подключения геокодера.' : '.'}</div>
          )}
        </div>
      )}
    </div>
  );
}
