export function ResetViewButton({ onReset }: { onReset: () => void }) {
  return <button className="btn" type="button" onClick={onReset}>Reset view</button>;
}
