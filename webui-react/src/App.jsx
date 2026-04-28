import React, { useState } from 'react';
import { 
  ChartBarIcon, 
  PlayIcon, 
  FolderIcon, 
  UserGroupIcon, 
  Cog6ToothIcon,
  CommandLineIcon,
  ChatBubbleLeftRightIcon,
} from '@heroicons/react/24/outline';

import Dashboard from './components/Dashboard';
import TaskPanel from './components/TaskPanel';
import DataExplorer from './components/DataExplorer';
import CommentViewer from './components/CommentViewer';
import AccountCenter from './components/AccountCenter';
import Settings from './components/Settings';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');

  const renderContent = () => {
    switch (activeTab) {
      case 'dashboard': return <Dashboard />;
      case 'task': return <TaskPanel />;
      case 'data': return <DataExplorer />;
      case 'comments': return <CommentViewer />;
      case 'account': return <AccountCenter />;
      case 'settings': return <Settings />;
      default: return <Dashboard />;
    }
  };

  return (
    <div className="flex h-screen overflow-hidden text-slate-200 bg-slate-950 font-sans selection:bg-blue-500/30">
      {/* Sidebar */}
      <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col shrink-0">
        <div className="p-8 flex items-center space-x-3 group cursor-pointer">
          <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-500/20 group-hover:scale-110 transition-transform">
            <CommandLineIcon className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-black tracking-tight bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">MediaCrawler</h1>
            <p className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Enterprise Edition</p>
          </div>
        </div>
        
        <nav className="flex-1 px-4 py-4 space-y-1.5 overflow-y-auto">
          <NavItem 
            icon={ChartBarIcon} 
            label="仪表盘" 
            active={activeTab === 'dashboard'} 
            onClick={() => setActiveTab('dashboard')} 
          />
          <NavItem 
            icon={PlayIcon} 
            label="采集工场" 
            active={activeTab === 'task'} 
            onClick={() => setActiveTab('task')} 
          />
          <NavItem 
            icon={FolderIcon} 
            label="数据中心" 
            active={activeTab === 'data'} 
            onClick={() => setActiveTab('data')} 
          />
          <NavItem
            icon={ChatBubbleLeftRightIcon}
            label="评论查看"
            active={activeTab === 'comments'}
            onClick={() => setActiveTab('comments')}
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

        <div className="p-4 m-4 bg-slate-800/30 rounded-2xl border border-slate-800/50 text-[10px] text-slate-500">
          <p className="font-bold flex items-center space-x-1 uppercase">
            <span className="w-1 h-1 bg-emerald-500 rounded-full animate-pulse" />
            <span>Server: localhost:8080</span>
          </p>
          <p className="mt-1">Version 2.0.0-alpha</p>
        </div>
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
