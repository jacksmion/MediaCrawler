import React, { useState, useEffect } from 'react';
import { Cog6ToothIcon, CloudArrowUpIcon, DocumentTextIcon, KeyIcon } from '@heroicons/react/24/outline';
import { Switch } from '@headlessui/react';

export default function Settings() {
  const [config, setConfig] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchConfig = async () => {
    try {
      const res = await fetch(`http://${window.location.hostname}:8080/api/config`);
      const data = await res.json();
      setConfig(data.config || {});
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfig();
  }, []);

  const handleUpdate = async () => {
    setSaving(true);
    try {
      const res = await fetch(`http://${window.location.hostname}:8080/api/config/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
      if (res.ok) {
        alert("配置已更新并在服务端生效！");
      }
    } catch (err) {
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const updateField = (key, value) => setConfig({ ...config, [key]: value });

  if (loading) return <div className="p-8 text-center text-slate-500">正在加载核心配置...</div>;

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold flex items-center space-x-2">
            <Cog6ToothIcon className="w-8 h-8 text-blue-500" />
            <span>配置中心</span>
          </h2>
          <p className="text-slate-500 text-sm mt-1">全局动态参数配置，修改后自动写回 config/base_config.py</p>
        </div>
        <button 
          onClick={handleUpdate}
          disabled={saving}
          className="flex items-center space-x-2 px-6 py-2.5 bg-blue-600 hover:bg-blue-500 rounded-xl transition-all shadow-lg shadow-blue-900/40 text-sm font-bold disabled:opacity-50"
        >
          {saving ? '保存中...' : <><CloudArrowUpIcon className="w-5 h-5" /><span>保存全局配置</span></>}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Basic Settings */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
          <h3 className="text-sm font-bold uppercase text-slate-500 tracking-wider flex items-center space-x-2">
            <DocumentTextIcon className="w-4 h-4" />
            <span>基础参数</span>
          </h3>
          
          <div className="space-y-4">
          <ConfigField label="数据保存格式" value={config.SAVE_DATA_OPTION}>
              <select 
                value={config.SAVE_DATA_OPTION}
                onChange={(e) => updateField('SAVE_DATA_OPTION', e.target.value)}
                className="bg-slate-950 border border-slate-800 rounded-lg p-2 w-full outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="jsonl">JSONL (默认推荐)</option>
                <option value="csv">CSV (通用表格)</option>
                <option value="db">DATABASE (数据库)</option>
              </select>
            </ConfigField>

            <ConfigField label="默认无头模式运行" value={config.HEADLESS}>
              <Switch checked={config.HEADLESS || false} onChange={(v) => updateField('HEADLESS', v)} className={`${config.HEADLESS ? 'bg-blue-600' : 'bg-slate-700'} relative inline-flex h-6 w-11 items-center rounded-full transition-colors`}>
                <span className={`${config.HEADLESS ? 'translate-x-6' : 'translate-x-1'} inline-block h-4 w-4 transform rounded-full bg-white transition-transform`} />
              </Switch>
            </ConfigField>

            <ConfigField label="并发量 (Concurrency)" value={config.CONCURRENCY}>
              <input type="number" value={config.CONCURRENCY} onChange={(e) => updateField('CONCURRENCY', parseInt(e.target.value))} className="bg-slate-950 border border-slate-800 rounded-lg p-2 w-full outline-none focus:ring-1 focus:ring-blue-500" />
            </ConfigField>

            <ConfigField label="最大尝试次数" value={config.MAX_RETRY}>
              <input type="number" value={config.MAX_RETRY} onChange={(e) => updateField('MAX_RETRY', parseInt(e.target.value))} className="bg-slate-950 border border-slate-800 rounded-lg p-2 w-full outline-none focus:ring-1 focus:ring-blue-500" />
            </ConfigField>
          </div>
        </div>

        {/* Crawler Specifics */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6 shadow-sm">
          <h3 className="text-sm font-bold uppercase text-slate-500 tracking-wider flex items-center space-x-2">
            <KeyIcon className="w-4 h-4" />
            <span>进阶采集方案</span>
          </h3>
          
          <div className="space-y-4">
            <ConfigField label="自动重试延时 (秒)" value={config.RETRY_INTERVAL}>
              <input type="number" value={config.RETRY_INTERVAL} onChange={(e) => updateField('RETRY_INTERVAL', parseInt(e.target.value))} className="bg-slate-950 border border-slate-800 rounded-lg p-2 w-full outline-none focus:ring-1 focus:ring-blue-500" />
            </ConfigField>

            <ConfigField label="抓取总数限制" value={config.CRAWLER_MAX_NOTES_COUNT}>
              <input type="number" value={config.CRAWLER_MAX_NOTES_COUNT} onChange={(e) => updateField('CRAWLER_MAX_NOTES_COUNT', parseInt(e.target.value))} className="bg-slate-950 border border-slate-800 rounded-lg p-2 w-full outline-none focus:ring-1 focus:ring-blue-500" />
            </ConfigField>
            
            <ConfigField label="获取二级评论" value={config.ENABLE_GET_SUB_COMMENTS}>
              <Switch checked={config.ENABLE_GET_SUB_COMMENTS || false} onChange={(v) => updateField('ENABLE_GET_SUB_COMMENTS', v)} className={`${config.ENABLE_GET_SUB_COMMENTS ? 'bg-blue-600' : 'bg-slate-700'} relative inline-flex h-6 w-11 items-center rounded-full transition-colors`}>
                <span className={`${config.ENABLE_GET_SUB_COMMENTS ? 'translate-x-6' : 'translate-x-1'} inline-block h-4 w-4 transform rounded-full bg-white transition-transform`} />
              </Switch>
            </ConfigField>
          </div>
        </div>
      </div>
    </div>
  );
}

function ConfigField({ label, children }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-slate-400">{label}</span>
      <div className="w-32 flex justify-end">
        {children}
      </div>
    </div>
  );
}
