import React, { useState } from 'react';
import {
  UserGroupIcon,
  Cog6ToothIcon,
  CommandLineIcon,
  Squares2X2Icon,
} from '@heroicons/react/24/outline';
import TaskCenter from './components/TaskCenter';
import AccountCenter from './components/AccountCenter';
import Settings from './components/Settings';

export default function App() {
  const [activeTab, setActiveTab] = useState('tasks');

  const renderContent = () => {
    switch (activeTab) {
      case 'tasks': return <TaskCenter />;
      case 'account': return <AccountCenter />;
      case 'settings': return <Settings />;
      default: return <TaskCenter />;
    }
  };

  return (
    <div className="flex h-screen overflow-hidden text-slate-200 bg-slate-950 font-sans selection:bg-blue-500/30">
      {/* Sidebar */}
      <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col shrink-0">

        
        <nav className="flex-1 px-4 py-4 space-y-1.5 overflow-y-auto">
          <NavItem
            icon={Squares2X2Icon}
            label="任务中心"
            active={activeTab === 'tasks'}
            onClick={() => setActiveTab('tasks')}
          />
          <NavItem
            icon={UserGroupIcon}
            label="账号管理"
            active={activeTab === 'account'}
            onClick={() => setActiveTab('account')}
          />
          <div className="pt-4 mt-4 border-t border-slate-800/50">
            <NavItem
              icon={Cog6ToothIcon}
              label="系统设置"
              active={activeTab === 'settings'}
              onClick={() => setActiveTab('settings')}
            />
          </div>
        </nav>
      </aside>

      {/* Main Area */}
      <main className="flex-1 flex flex-col min-w-0">
        <div className="flex-1 overflow-auto bg-[radial-gradient(circle_at_top_right,_var(--tw-gradient-stops))] from-slate-900/40 via-transparent to-transparent">
          {renderContent()}
        </div>
      </main>
    </div>
  );
}

function NavItem(props) {
  const { icon: Icon, label, active, onClick } = props;
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center space-x-3 px-4 py-3 rounded-2xl transition-all duration-300 relative group ${
        active 
          ? 'bg-blue-600/10 text-blue-400 font-bold shadow-sm' 
          : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-200'
      }`}
    >
      {active && (
        <div className="absolute left-0 w-1 h-6 bg-blue-500 rounded-r-full shadow-lg shadow-blue-500/50" />
      )}
      <Icon className={`w-5 h-5 transition-transform group-hover:scale-110 ${active ? 'text-blue-500' : 'text-slate-500 group-hover:text-slate-300'}`} />
      <span className="text-sm tracking-wide">{label}</span>
      {!active && (
         <div className="absolute right-4 opacity-0 group-hover:opacity-100 transition-opacity">
            <div className="w-1 h-1 bg-slate-600 rounded-full" />
         </div>
      )}
    </button>
  );
}
