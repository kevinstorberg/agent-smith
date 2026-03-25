import { NavLink } from 'react-router';

const HARNESS_LINKS = [
  { path: '/harness/rules', label: 'Rules' },
  { path: '/harness/skills', label: 'Skills' },
  { path: '/harness/tools', label: 'Tools' },
  { path: '/harness/hooks', label: 'Hooks' },
];

function navClass({ isActive }: { isActive: boolean }): string {
  return `sidebar-link${isActive ? ' active' : ''}`;
}

export function Sidebar() {
  return (
    <nav className="sidebar">
      <div className="sidebar-title">Agent Smith</div>

      <div className="sidebar-section">
        <div className="section-header">Harness</div>
        {HARNESS_LINKS.map(link => (
          <NavLink key={link.path} to={link.path} className={navClass}>
            {link.label}
          </NavLink>
        ))}
      </div>

      <div className="sidebar-section">
        <NavLink to="/memory" className={navClass}>Memory</NavLink>
        <NavLink to="/evals" className={navClass}>Evals</NavLink>
      </div>
    </nav>
  );
}
