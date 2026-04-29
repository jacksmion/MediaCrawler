import React, { useState, useEffect } from 'react';
import { UserCircleIcon, CheckCircleIcon, XCircleIcon, ArrowPathIcon, PlusIcon, TrashIcon } from '@heroicons/react/24/outline';

const PLATFORMS = [
  { id: 'xhs', name: '小红书', color: 'text-rose-500' },
  { id: 'dy', name: '抖音', color: 'text-emerald-500' },
  { id: 'ks', name: '快手', color: 'text-orange-500' },
  { id: 'bili', name: 'B站', color: 'text-pink-500' },
  { id: 'wb', name: '微博', color: 'text-red-500' },
  { id: 'tieba', name: '贴吧', color: 'text-blue-500' },
  { id: 'zhihu', name: '知乎', color: 'text-indigo-500' },
];

const API_BASE = `http://${window.location.hostname}:8080`;

export default function AccountCenter() {
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [addForm, setAddForm] = useState({ platform: 'dy', name: '', remark: '' });
  const [loginLoading, setLoginLoading] = useState({});

  const fetchAccounts = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/account/list`);
      const data = await res.json();
      setAccounts(data.accounts || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAccounts(); }, []);

  const handleAdd = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/account/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(addForm),
      });
      if (res.ok) {
        setShowAddModal(false);
        setAddForm({ platform: 'dy', name: '', remark: '' });
        await fetchAccounts();
      } else {
        const data = await res.json();
        alert('错误: ' + data.detail);
      }
    } catch (err) {
      console.error(err);
      alert('添加账号失败');
    }
  };

  const handleDelete = async (accountId, accountName) => {
    if (!confirm(`确定要删除账号「${accountName}」吗？登录数据将被清除。`)) return;
    try {
      const res = await fetch(`${API_BASE}/api/account/${accountId}`, { method: 'DELETE' });
      if (res.ok) {
        await fetchAccounts();
      } else {
        const data = await res.json();
        alert('错误: ' + data.detail);
      }
    } catch (err) {
      console.error(err);
      alert('删除失败');
    }
  };

  const handleLogin = async (accountId) => {
    setLoginLoading(prev => ({ ...prev, [accountId]: true }));
    try {
      const res = await fetch(`${API_BASE}/api/account/${accountId}/login`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        alert(data.message);
      } else {
        alert('错误: ' + (data.detail || data.message));
      }
    } catch (err) {
      console.error(err);
      alert('请求发送失败');
    } finally {
      setLoginLoading(prev => ({ ...prev, [accountId]: false }));
    }
  };

  // Group accounts by platform
  const grouped = {};
  for (const p of PLATFORMS) {
    grouped[p.id] = accounts.filter(a => a.platform === p.id);
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">账号管理</h2>
          <p className="text-slate-500 text-sm mt-1">管理各平台的登录账号，支持多账号并发</p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            onClick={fetchAccounts}
            disabled={loading}
            className="flex items-center space-x-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors text-sm font-medium"
          >
            <ArrowPathIcon className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            <span>刷新状态</span>
          </button>
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center space-x-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors text-sm font-bold"
          >
            <PlusIcon className="w-4 h-4" />
            <span>添加账号</span>
          </button>
        </div>
      </div>

      {PLATFORMS.map(platform => {
        const platformAccounts = grouped[platform.id] || [];
        return (
          <div key={platform.id}>
            <div className="flex items-center space-x-2 mb-3">
              <span className={`text-sm font-bold ${platform.color}`}>{platform.name}</span>
              <span className="text-xs text-slate-600">({platform.id})</span>
              {platformAccounts.length === 0 && (
                <span className="text-xs text-slate-600 ml-2">暂无账号</span>
              )}
            </div>
            {platformAccounts.length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                {platformAccounts.map(account => (
                  <div key={account.account_id} className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3 hover:border-slate-700 transition-all">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center space-x-3">
                        <div className={`p-2.5 rounded-xl bg-slate-800 ${account.status === 'active' ? platform.color : 'text-slate-600'}`}>
                          <UserCircleIcon className="w-6 h-6" />
                        </div>
                        <div>
                          <h3 className="font-bold">{account.name}</h3>
                          <span className="text-xs text-slate-500 font-mono">{account.account_id}</span>
                        </div>
                      </div>
                      {account.status === 'active' ? (
                        <div className="flex items-center text-emerald-500 space-x-1">
                          <CheckCircleIcon className="w-4 h-4" />
                          <span className="text-xs font-bold">Active</span>
                        </div>
                      ) : (
                        <div className="flex items-center text-slate-600 space-x-1">
                          <XCircleIcon className="w-4 h-4" />
                          <span className="text-xs">未登录</span>
                        </div>
                      )}
                    </div>

                    <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
                      <span className="text-xs text-slate-500">最后活跃</span>
                      <span className="text-xs text-slate-400">
                        {account.last_active ? new Date(account.last_active * 1000).toLocaleString() : '从未登录'}
                      </span>
                    </div>

                    <div className="flex space-x-2">
                      <button
                        onClick={() => handleLogin(account.account_id)}
                        disabled={loginLoading[account.account_id]}
                        className={`flex-1 py-2 rounded-xl text-xs font-bold transition-all ${
                          account.status === 'active'
                            ? 'bg-slate-800 hover:bg-slate-700 text-slate-300'
                            : 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-900/40'
                        }`}
                      >
                        {loginLoading[account.account_id] ? '启动中...' : (account.status === 'active' ? '重新登录' : '扫码登录')}
                      </button>
                      <button
                        onClick={() => handleDelete(account.account_id, account.name)}
                        className="px-3 py-2 bg-slate-800 hover:bg-red-900/40 text-slate-400 hover:text-red-400 rounded-xl text-xs transition-all"
                      >
                        <TrashIcon className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {/* Add Account Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6 w-full max-w-md space-y-5">
            <h3 className="text-lg font-bold">添加账号</h3>

            <div>
              <label className="block text-xs text-slate-400 mb-1">平台</label>
              <select
                value={addForm.platform}
                onChange={e => setAddForm(f => ({ ...f, platform: e.target.value }))}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                {PLATFORMS.map(p => (
                  <option key={p.id} value={p.id}>{p.name} ({p.id})</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">账号名称</label>
              <input
                type="text"
                value={addForm.name}
                onChange={e => setAddForm(f => ({ ...f, name: e.target.value }))}
                placeholder="如：工作号、小号"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm placeholder-slate-600"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">备注</label>
              <input
                type="text"
                value={addForm.remark}
                onChange={e => setAddForm(f => ({ ...f, remark: e.target.value }))}
                placeholder="可选"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm placeholder-slate-600"
              />
            </div>

            <div className="flex space-x-3 pt-2">
              <button
                onClick={() => setShowAddModal(false)}
                className="flex-1 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm font-medium transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleAdd}
                className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-bold transition-colors"
              >
                确认添加
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
