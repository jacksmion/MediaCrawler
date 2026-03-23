import React, { useState, useEffect } from 'react';
import { UserCircleIcon, CheckCircleIcon, XCircleIcon, ArrowPathIcon } from '@heroicons/react/24/outline';

export default function AccountCenter() {
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(false);

  const fetchStatus = async () => {
    setLoading(true);
    try {
      const res = await fetch(`http://${window.location.hostname}:8080/api/account/status`);
      const data = await res.json();
      setAccounts(data.accounts || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">账号管理</h2>
          <p className="text-slate-500 text-sm mt-1">监测各媒体平台的登录持久化状态</p>
        </div>
        <button 
          onClick={fetchStatus}
          disabled={loading}
          className="flex items-center space-x-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors text-sm font-medium"
        >
          <ArrowPathIcon className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          <span>刷新状态</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {accounts.map((account) => (
          <div key={account.platform} className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 hover:border-slate-700 transition-all shadow-sm">
            <div className="flex items-start justify-between">
              <div className="flex items-center space-x-4">
                <div className={`p-3 rounded-xl bg-slate-800 ${account.is_logged_in ? getPlatformColor(account.platform) : 'text-slate-600'}`}>
                  <UserCircleIcon className="w-8 h-8" />
                </div>
                <div>
                  <h3 className="font-bold text-lg uppercase">{account.platform}</h3>
                  <span className="text-xs text-slate-500 uppercase tracking-widest">{account.login_type || 'NONE'}</span>
                </div>
              </div>
              {account.is_logged_in ? (
                <div className="flex items-center text-emerald-500 space-x-1">
                  <CheckCircleIcon className="w-5 h-5" />
                  <span className="text-xs font-bold uppercase">Active</span>
                </div>
              ) : (
                <div className="flex items-center text-slate-600 space-x-1">
                  <XCircleIcon className="w-5 h-5" />
                  <span className="text-xs font-bold uppercase">Logged Out</span>
                </div>
              )}
            </div>
            
            <div className="pt-4 border-t border-slate-800 flex items-center justify-between">
              <span className="text-xs text-slate-500">最后活跃时间</span>
              <span className="text-xs text-slate-400">
                {account.last_active ? new Date(account.last_active * 1000).toLocaleString() : '从未登录'}
              </span>
            </div>

            <button 
              className={`w-full py-2 rounded-xl text-sm font-bold transition-all ${account.is_logged_in ? 'bg-slate-800 hover:bg-slate-700 text-slate-300' : 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-900/40'}`}
            >
              {account.is_logged_in ? '重新登录' : '拉起登录扫码'}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function getPlatformColor(platform) {
  switch (platform) {
    case 'xhs': return 'text-rose-500';
    case 'dy': return 'text-emerald-500';
    case 'ks': return 'text-orange-500';
    case 'bili': return 'text-pink-500';
    case 'wb': return 'text-red-500';
    default: return 'text-blue-500';
  }
}
