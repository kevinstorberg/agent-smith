import { Link } from 'react-router';
import type { ComponentProps } from 'react';
import './buttonLink.css';

export function ButtonLink({
  className = '',
  ...props
}: ComponentProps<typeof Link>) {
  return <Link {...props} className={`btn ${className} button-link`.trim()} />;
}
