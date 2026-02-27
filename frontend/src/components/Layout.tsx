import { Outlet, Link, useLocation } from 'react-router-dom';
import { LayersIcon, BarChartIcon, ComponentInstanceIcon } from '@radix-ui/react-icons';
import { cn } from '../lib/utils';

export function Layout() {
  const location = useLocation();

  const navItems = [
    { name: 'Overview', path: '/', icon: LayersIcon },
    { name: 'Analytics', path: '/analytics', icon: BarChartIcon },
    { name: 'Jobs', path: '/jobs', icon: ComponentInstanceIcon },
  ];

  return (
    <div className="flex h-screen bg-gray-50 text-gray-900 font-sans">
      <div className="w-64 border-r border-gray-200 bg-white shadow-sm flex flex-col">
        <div className="p-6">
          <h1 className="text-xl font-bold bg-gradient-to-r from-primary-600 to-primary-400 bg-clip-text text-transparent flex items-center gap-2">
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
                    ? 'bg-primary-50 text-primary-700 font-semibold'
                    : 'text-gray-500 hover:text-gray-900 hover:bg-gray-100'
                )}
              >
                <Icon className="w-4 h-4" />
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex-1 overflow-auto bg-gray-50">
        <main className="p-8 max-w-7xl mx-auto min-h-full">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
