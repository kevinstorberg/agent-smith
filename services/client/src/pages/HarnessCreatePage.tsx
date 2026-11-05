import { Link, useLocation } from 'react-router';
import { TYPE_PATHS } from '../constants';
import { harnessStyles as styles } from '../styles/harness';
import { HarnessEditor } from '../components/HarnessEditor';

function typeFromPath(pathname: string): string {
  const match = pathname.match(/\/harness\/(\w+)\/new/);
  return match ? match[1] : 'rule';
}

export function HarnessCreatePage() {
  const { pathname } = useLocation();
  const type = typeFromPath(pathname);
  const list = TYPE_PATHS[type] || `${type}s`;
  return (
    <div>
      <div style={styles.header}>
        <Link className="detail-back" to={`/harness/${list}`}>
          &larr; Back to {list}
        </Link>
      </div>
      <HarnessEditor key={type} kind={type} />
    </div>
  );
}
