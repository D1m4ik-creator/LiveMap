export function pluralRu(count: number, one: string, few: string, many: string): string {
  const value = count % 100;
  return count % 10 === 1 && value !== 11 ? one
    : count % 10 >= 2 && count % 10 <= 4 && (value < 12 || value > 14) ? few : many;
}
