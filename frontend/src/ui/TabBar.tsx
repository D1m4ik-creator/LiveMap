export function TabBar<T extends string>({ items, value, onChange, label }: {
  items: readonly { id: T; label: string }[];
  value: T; onChange: (value: T) => void; label: string;
}) {
  return <nav className="admin-tabs" aria-label={label}>{items.map((item) =>
    <button key={item.id} type="button" className={value === item.id ? 'active' : ''}
      aria-current={value === item.id ? 'page' : undefined} onClick={() => onChange(item.id)}>{item.label}</button>,
  )}</nav>;
}
