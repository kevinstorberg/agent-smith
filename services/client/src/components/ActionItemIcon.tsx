const paths = {
  top: 'M12 19V7m-5 5 5-5 5 5M5 4h14',
  bottom: 'M12 5v12m-5-5 5 5 5-5M5 20h14',
  complete: 'm5 12 4 4L19 6',
  reopen: 'M3 10a9 9 0 1 1 2.4 8.1M3 4v6h6',
  edit: 'm16 4 4 4M4 20l4-1L20 7a2.1 2.1 0 0 0-3-3L5 16l-1 4',
  delete: 'M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6m4-6v6',
};

export function ActionItemIcon({ name }: { name: keyof typeof paths }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={paths[name]} />
    </svg>
  );
}
