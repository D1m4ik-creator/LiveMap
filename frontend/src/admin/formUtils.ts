export function changedFields<T extends object>(original: T, current: T): Partial<T> {
  return Object.fromEntries(Object.entries(current).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(original[key as keyof T]))) as Partial<T>;
}

export function localDate(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function apiDate(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}
