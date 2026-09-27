import type { ReactNode } from 'react';

export function FormField({ id, label, hint, wide = false, children }: {
  id: string; label: string; hint?: string; wide?: boolean; children: ReactNode;
}) {
  return <div className={`field${wide ? ' wide' : ''}`}><label htmlFor={id}>{label}</label>{children}{hint && <small>{hint}</small>}</div>;
}
