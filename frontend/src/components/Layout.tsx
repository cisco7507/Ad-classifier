import { Outlet, Link, useLocation } from 'react-router-dom';
import { LayersIcon, ComponentInstanceIcon } from '@radix-ui/react-icons';
import { cn } from '../lib/utils';

export function Layout() {
  const location = useLocation();

  const navItems = [
    { name: 'Overview', path: '/', icon: LayersIcon },
    { name: 'Jobs', path: '/jobs', icon: ComponentInstanceIcon },
  ];

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 font-sans">
      <div className="w-64 border-r border-slate-800 bg-slate-900 flex flex-col">
        <div className="p-6">
          <h1 className="text-xl font-bold bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent flex items-center gap-2">
            Ad Classifier
          </h1>
        </div>
        <nav className="flex-1 px-4 space-y-2">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path || (item.path !== '/' && location.pathname.startsWith(item.path));
            return (
              <Link
                key={item.name}
                to={item.path}
                className={cn(
                  'flex items-center gap-3 px-3 py-2 rounded-md transition-colors font-medium',
                  isActive
                    ? 'bg-primary-500/10 text-primary-400'
                    : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'
                )}
              >
                <Icon className="w-4 h-4" />
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex-1 overflow-auto bg-slate-950/50 backdrop-blur-3xl">
        <main className="p-8 max-w-7xl mx-auto min-h-full">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
