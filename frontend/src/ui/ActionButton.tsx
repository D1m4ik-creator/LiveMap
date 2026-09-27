import type { ButtonHTMLAttributes } from 'react';

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' };

export function ActionButton({ variant = 'secondary', className = '', type = 'button', ...props }: Props) {
  const variantClass = variant === 'primary' ? 'admin-primary' : variant === 'danger' ? 'admin-secondary admin-danger' : 'admin-secondary';
  return <button {...props} type={type} className={`${variantClass} ${className}`.trim()} />;
}
