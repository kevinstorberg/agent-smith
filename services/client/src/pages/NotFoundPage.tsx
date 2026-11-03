import { Link } from 'react-router';

export function NotFoundPage() {
  return <section aria-labelledby="not-found-title">
    <div className="page-header"><h2 id="not-found-title" className="page-title">Page not found</h2></div>
    <div className="card">
      <p>This address does not match a page. Choose a section from the sidebar or return to your action items.</p>
      <Link className="btn btn-primary" to="/action-items">Open action items</Link>
    </div>
  </section>;
}
