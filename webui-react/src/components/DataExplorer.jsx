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
  const [previewType, setPreviewType] = useState('contents'); // contents or comments
  
  const formatDate = (ts) => {
    if (!ts) return '-';
    // Handle both seconds and milliseconds
    const date = ts > 10000000000 ? new Date(ts) : new Date(ts * 1000);
    return date.toLocaleString();
  };

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
      // Determine type from filename
      setPreviewType(path.includes('comments') ? 'comments' : 'contents');
      const res = await fetch(`http://${window.location.hostname}:8080/api/data/files/${encodeURIComponent(path)}?preview=true`);
      const data = await res.json();
      setFiles(prev => prev.map(f => f.path === path ? { ...f, previewed: true } : f));
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
              <div className="flex items-center space-x-4">
                <h3 className="font-bold">数据预览</h3>
                <span className="text-xs bg-slate-800 text-slate-400 px-2 py-0.5 rounded-full border border-slate-700 uppercase tracking-tighter font-bold">
                  {previewType === 'comments' ? '评论数据' : '笔记/视频内容'}
                </span>
              </div>
              <button onClick={() => setPreviewContent(null)} className="text-slate-500 hover:text-white bg-slate-800 p-1.5 rounded-lg transition-colors">✕</button>
            </div>
            <div className="flex-1 overflow-auto bg-slate-950">
              <table className="w-full text-left text-xs border-collapse">
                <thead className="sticky top-0 bg-slate-900 border-b border-slate-800 z-10 text-slate-500 font-bold uppercase tracking-wider">
                  <tr>
                    {previewType === 'comments' ? (
                      <>
                        <th className="px-6 py-3 w-48">博主信息</th>
                        <th className="px-6 py-3">评论内容</th>
                        <th className="px-6 py-3 w-24">获赞</th>
                        <th className="px-6 py-3 w-48">时间</th>
                      </>
                    ) : (
                      <>
                        <th className="px-6 py-3 w-48">作者信息</th>
                        <th className="px-6 py-3">内容概要</th>
                        <th className="px-6 py-3 w-32">互动数据</th>
                        <th className="px-6 py-3 w-48">发布时间</th>
                      </>
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {previewContent.map((item, idx) => (
                    <tr key={idx} className="hover:bg-slate-900/40 transition-colors">
                      {previewType === 'comments' ? (
                        <>
                          <td className="px-6 py-4">
                            <div className="flex items-center space-x-2">
                              {item.avatar && <img src={item.avatar} className="w-8 h-8 rounded-full border border-slate-700 shadow-sm" alt="" />}
                              <div className="flex flex-col">
                                <span className="font-bold text-slate-300 truncate max-w-[120px]">{item.nickname || 'Unknown'}</span>
                                <span className="text-[9px] text-slate-500 font-mono">UID: {item.user_id}</span>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <p className="text-slate-200 line-clamp-3 leading-relaxed">{item.content}</p>
                            {item.ip_location && <span className="text-[10px] text-slate-500 mt-1 block">📍 {item.ip_location}</span>}
                          </td>
                          <td className="px-6 py-4 text-emerald-500 font-mono font-bold">{item.like_count || 0}</td>
                          <td className="px-6 py-4 text-slate-500 whitespace-nowrap">{formatDate(item.create_time)}</td>
                        </>
                      ) : (
                        <>
                          <td className="px-6 py-4">
                            <div className="flex items-center space-x-2">
                              {item.avatar && <img src={item.avatar} className="w-8 h-8 rounded-full border border-slate-700 shadow-sm" alt="" />}
                              <div className="flex flex-col">
                                <span className="font-bold text-slate-300 truncate max-w-[100px]">{item.nickname || 'Unknown'}</span>
                                <span className="text-[9px] text-slate-500">ID: {item.user_id}</span>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="space-y-1">
                              {item.title && <h4 className="font-bold text-slate-200 line-clamp-1">{item.title}</h4>}
                              <p className="text-slate-400 line-clamp-2 leading-tight">{item.desc}</p>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="grid grid-cols-1 gap-1 text-[10px] text-slate-400">
                              <span className="flex justify-between"><span>👍</span> {item.liked_count || 0}</span>
                              <span className="flex justify-between"><span>💬</span> {item.comment_count || 0}</span>
                              {item.share_count && <span className="flex justify-between"><span>🔗</span> {item.share_count}</span>}
                            </div>
                          </td>
                          <td className="px-6 py-4 text-slate-500 whitespace-nowrap">{formatDate(item.time)}</td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="p-3 bg-slate-900 border-t border-slate-800 text-[10px] text-center text-slate-500 italic">
              * 目前仅展示最近采集的前 10 条数据进行预览，完整内容请下载文件查看
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
