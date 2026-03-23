import React, { useState, useEffect } from 'react';
import { FolderIcon, DocumentIcon, ArrowDownTrayIcon, MagnifyingGlassIcon, EyeIcon } from '@heroicons/react/24/outline';

const DATA_DIR_MAPPING = {
  xhs: '小红书',
  dy: '抖音',
  ks: '快手',
  bili: 'Bilibili',
  wb: '新浪微博',
  tieba: '百度贴吧',
  zhihu: '知乎',
};

export default function DataExplorer() {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [previewContent, setPreviewContent] = useState(null);

  const fetchFiles = async () => {
    try {
      const res = await fetch(`http://${window.location.hostname}:8080/api/data/files`);
      const data = await res.json();
      setFiles(data.files || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFiles();
  }, []);

  const handlePreview = async (path) => {
    try {
      const res = await fetch(`http://${window.location.hostname}:8080/api/data/files/${encodeURIComponent(path)}?preview=true`);
      const data = await res.json();
      setPreviewContent(data.data || []);
    } catch (err) {
      console.error(err);
    }
  };

  const filteredFiles = files.filter(f => f.name.toLowerCase().includes(searchTerm.toLowerCase()));

  return (
    <div className="p-8 h-full flex flex-col space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">数据中心</h2>
        <div className="relative">
          <MagnifyingGlassIcon className="w-5 h-5 absolute left-3 top-2.5 text-slate-500" />
          <input 
            type="text" 
            placeholder="搜索文件..." 
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-10 pr-4 py-2 bg-slate-900 border border-slate-800 rounded-xl outline-none focus:ring-1 focus:ring-blue-500 w-64 transition-all"
          />
        </div>
      </div>

      <div className="flex-1 overflow-auto bg-slate-900 border border-slate-800 rounded-2xl shadow-sm">
        <table className="w-full text-left text-sm border-collapse">
          <thead className="sticky top-0 bg-slate-800/80 backdrop-blur text-slate-400 uppercase tracking-widest text-[10px] font-bold">
            <tr>
              <th className="px-6 py-4">文件名</th>
              <th className="px-6 py-4">记录数</th>
              <th className="px-6 py-4">大小</th>
              <th className="px-6 py-4">修改时间</th>
              <th className="px-6 py-4 text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {filteredFiles.map((file) => (
              <tr key={file.path} className="hover:bg-slate-800/40 transition-colors group">
                <td className="px-6 py-4 flex items-center space-x-3">
                  <DocumentIcon className="w-5 h-5 text-blue-500" />
                  <div className="flex flex-col">
                    <span className="font-medium text-slate-200">{file.name}</span>
                    <span className="text-[9px] w-fit px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-bold border border-slate-700 mt-1 uppercase">
                      {DATA_DIR_MAPPING[file.path.split(/[/\\]/)[0]] || 'Unknown'}
                    </span>
                  </div>
                </td>
                <td className="px-6 py-4 text-slate-400 font-mono text-xs">{file.record_count || '-'}</td>
                <td className="px-6 py-4 text-slate-400">{(file.size / 1024).toFixed(1)} KB</td>
                <td className="px-6 py-4 text-slate-500">{new Date(file.modified_at * 1000).toLocaleString()}</td>
                <td className="px-6 py-4 text-right space-x-2">
                  <button 
                    onClick={() => handlePreview(file.path)}
                    className="p-2 text-slate-400 hover:text-blue-400 transition-colors"
                    title="预览数据"
                  >
                    <EyeIcon className="w-5 h-5" />
                  </button>
                  <a 
                    href={`http://${window.location.hostname}:8080/api/data/download/${encodeURIComponent(file.path)}`}
                    target="_blank"
                    className="p-2 text-slate-400 hover:text-emerald-400 inline-block transition-colors"
                    title="下载文件"
                  >
                    <ArrowDownTrayIcon className="w-5 h-5" />
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filteredFiles.length === 0 && (
          <div className="p-12 text-center text-slate-600">
            {loading ? '正在同步云端文件数据...' : '未找到相关采集文件'}
          </div>
        )}
      </div>

      {previewContent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-8 bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-700 w-full max-w-6xl max-h-[80vh] rounded-3xl flex flex-col shadow-2xl overflow-hidden">
            <div className="p-4 border-b border-slate-800 flex justify-between items-center px-8">
              <h3 className="font-bold">数据预览 (最近 10 条)</h3>
              <button onClick={() => setPreviewContent(null)} className="text-slate-500 hover:text-white">✕</button>
            </div>
            <div className="flex-1 overflow-auto p-4 bg-slate-950 font-mono text-xs">
              <pre className="text-blue-400">
                {JSON.stringify(previewContent, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
