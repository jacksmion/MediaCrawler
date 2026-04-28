import React, { useState, useEffect, useRef } from 'react';
import { Listbox, Transition, Switch } from '@headlessui/react';
import { 
  CheckIcon, 
  ChevronUpDownIcon, 
  PlayIcon, 
  StopIcon, 
  CommandLineIcon
} from '@heroicons/react/20/solid';

const PLATFORMS = [
  { id: 'xhs', name: '小红书', color: 'text-rose-500' },
  { id: 'dy', name: '抖音', color: 'text-emerald-500' },
  { id: 'ks', name: '快手', color: 'text-orange-500' },
  { id: 'bili', name: 'Bilibili', color: 'text-pink-500' },
  { id: 'wb', name: '微博', color: 'text-red-500' },
];

const MODES = [
  { id: 'search', name: '关键词搜索', desc: '根据关键字抓取相关帖子' },
  { id: 'creator', name: '博主主页', desc: '抓取指定博主的所有作品' },
  { id: 'detail', name: '详情模式', desc: '根据指定 ID 抓取详情' },
];

export default function TaskPanel() {
  const [selectedPlatform, setSelectedPlatform] = useState(PLATFORMS[0]);
  const [selectedMode, setSelectedMode] = useState(MODES[0]);
  const [keywords, setKeywords] = useState('');
  const [logs, setLogs] = useState([]);
  const [isRunning, setIsRunning] = useState(false);
  const [headless, setHeadless] = useState(false);
  const [sortType, setSortType] = useState('general');
  const [commentTime, setCommentTime] = useState(0);
  const [filterKeywords, setFilterKeywords] = useState('');
  
  const logEndRef = useRef(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  useEffect(() => {
    const wsUrl = `ws://${window.location.hostname}:8080/api/ws/logs`;
    const statusUrl = `ws://${window.location.hostname}:8080/api/ws/status`;
    
    const logWs = new WebSocket(wsUrl);
    logWs.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setLogs(prev => [...prev.slice(-100), data]);
    };

    const statusWs = new WebSocket(statusUrl);
    statusWs.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setIsRunning(data.status === 'running');
    };

    return () => {
      logWs.close();
      statusWs.close();
    };
  }, []);

  const handleStart = async () => {
    try {
      const payload = {
        platform: selectedPlatform.id,
        login_type: 'qrcode',
        crawler_type: selectedMode.id,
        headless: headless,
        save_option: 'jsonl',
        start_page: 1,
        enable_comments: true,
        enable_sub_comments: false,
        sort_type: sortType,
        comment_time_filter_h: parseInt(commentTime) || 0,
        keywords: selectedMode.id === 'search' ? keywords : filterKeywords
      };

      // Map input value to correct backend field
      if (selectedMode.id === 'creator') {
        payload.creator_ids = keywords;
      } else if (selectedMode.id === 'detail') {
        payload.specified_ids = keywords;
      }

      await fetch(`http://${window.location.hostname}:8080/api/crawler/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } catch (err) { console.error(err); }
  };

  const handleStop = async () => {
    await fetch(`http://${window.location.hostname}:8080/api/crawler/stop`, { method: 'POST' });
  };

  const handlePlatformChange = (platform) => {
    setSelectedPlatform(platform);
    setSortType(platform.id === 'dy' ? '0' : 'general');
  };

  return (
    <div className="p-8 max-w-4xl mx-auto w-full space-y-8">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div className="space-y-4">
          <label className="block text-sm font-medium text-slate-400">媒体平台</label>
          <Listbox value={selectedPlatform} onChange={handlePlatformChange}>
            <div className="relative mt-1">
              <Listbox.Button className="relative w-full cursor-default rounded-xl bg-slate-900 py-3 pl-4 pr-10 text-left border border-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all hover:bg-slate-800 transition-colors">
                <span className="block truncate font-medium">{selectedPlatform.name}</span>
                <span className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2">
                  <ChevronUpDownIcon className="h-5 h-5 text-slate-500" />
                </span>
              </Listbox.Button>
              <Transition as={React.Fragment} leave="transition ease-in duration-100" leaveFrom="opacity-100" leaveTo="opacity-0">
                <Listbox.Options className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-xl bg-slate-900 py-1 shadow-2xl ring-1 ring-black ring-opacity-5 focus:outline-none border border-slate-800">
                  {PLATFORMS.map((p) => (
                    <Listbox.Option key={p.id} value={p} className={({ active }) => `relative cursor-default select-none py-2 pl-10 pr-4 ${active ? 'bg-blue-600/20 text-blue-400' : 'text-slate-300'}`}>
                      {({ selected }) => (
                        <>
                          <span className={`block truncate ${selected ? 'font-semibold text-blue-400' : 'font-normal'}`}>{p.name}</span>
                          {selected ? <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-blue-500"><CheckIcon className="h-5 w-5" /></span> : null}
                        </>
                      )}
                    </Listbox.Option>
                  ))}
                </Listbox.Options>
              </Transition>
            </div>
          </Listbox>
        </div>

        <div className="space-y-4">
          <label className="block text-sm font-medium text-slate-400">采集模式</label>
          <div className="grid grid-cols-1 gap-2">
            {MODES.map((mode) => (
              <button
                key={mode.id}
                onClick={() => setSelectedMode(mode)}
                className={`flex items-start text-left p-3 rounded-xl border transition-all ${selectedMode.id === mode.id ? 'bg-blue-600/10 border-blue-500/50' : 'bg-slate-900/50 border-slate-800 hover:border-slate-700'}`}
              >
                <div>
                  <p className={`text-sm font-semibold ${selectedMode.id === mode.id ? 'text-blue-400' : 'text-slate-200'}`}>{mode.name}</p>
                  <p className="text-xs text-slate-500 mt-0.5">{mode.desc}</p>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <label className="block text-sm font-medium text-slate-400">
          {selectedMode.id === 'search' ? '采集关键词' : 
           selectedMode.id === 'creator' ? '博主 ID' : '帖子 ID'}
        </label>
        <input 
          type="text" 
          value={keywords}
          onChange={(e) => setKeywords(e.target.value)}
          placeholder={selectedMode.id === 'search' ? '例如: 露营, 户外装备' : 
                      selectedMode.id === 'creator' ? '例如: 5fed0cf1000000000100650e (多个用英文逗号分隔)' : 
                      '例如: 650085d5000000001201732e (多个用英文逗号分隔)'}
          className="w-full bg-slate-900 border border-slate-800 rounded-xl py-3 px-4 focus:ring-2 focus:ring-blue-500 outline-none transition-all"
        />
      </div>

      <div className="flex items-center justify-between p-4 bg-slate-900/40 rounded-2xl border border-slate-800/50">
        <div className="flex flex-col space-y-4 w-full">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <Switch checked={headless} onChange={setHeadless} className={`${headless ? 'bg-blue-600' : 'bg-slate-700'} relative inline-flex h-6 w-11 items-center rounded-full transition-colors`}>
                <span className={`${headless ? 'translate-x-6' : 'translate-x-1'} inline-block h-4 w-4 transform rounded-full bg-white transition-transform`} />
              </Switch>
              <span className="text-sm font-medium">无头浏览器模式</span>
            </div>

            <div className="flex space-x-3">
              <button 
                onClick={isRunning ? handleStop : handleStart}
                className={`px-8 py-3 rounded-xl font-bold flex items-center space-x-2 transition-all active:scale-95 shadow-lg ${isRunning ? 'bg-rose-600 hover:bg-rose-500 shadow-rose-900/40' : 'bg-blue-600 hover:bg-blue-500 shadow-blue-900/40'}`}
              >
                {isRunning ? <><StopIcon className="w-5 h-5" /><span>停止任务</span></> : <><PlayIcon className="w-5 h-5" /><span>开始任务</span></>}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4 border-t border-slate-800/50">
            {selectedMode.id === 'search' && (
              <div className="space-y-2">
                <label className="text-[10px] uppercase tracking-wider font-bold text-slate-500">搜索排序规则</label>
                <select 
                  value={sortType} 
                  onChange={(e) => setSortType(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg py-2 px-3 text-sm focus:ring-1 focus:ring-blue-500 outline-none"
                >
                  {selectedPlatform.id === 'xhs' ? (
                    <>
                      <option value="general">综合排序</option>
                      <option value="popularity_descending">最热优先</option>
                      <option value="time_descending">最新优先</option>
                    </>
                  ) : (
                    <>
                      <option value="0">综合排序</option>
                      <option value="1">点赞最多</option>
                      <option value="2">最新发布</option>
                    </>
                  )}
                </select>
              </div>
            )}
            
            <div className="space-y-2">
              <label className="text-[10px] uppercase tracking-wider font-bold text-slate-500">评论时间限制 (小时)</label>
              <div className="flex items-center space-x-2">
                <input 
                  type="number" 
                  min="0"
                  value={commentTime}
                  onChange={(e) => setCommentTime(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg py-2 px-3 text-sm focus:ring-1 focus:ring-blue-500 outline-none"
                />
                <span className="text-[10px] text-slate-500 whitespace-nowrap">0表示不限</span>
              </div>
            </div>

            {selectedMode.id !== 'search' && (
              <div className="space-y-2 md:col-span-2">
                <label className="text-[10px] uppercase tracking-wider font-bold text-slate-500">内容关键词过滤 (可选)</label>
                <input 
                  type="text" 
                  placeholder="仅采集标题或正文包含此关键字的作品，多个用英文逗号分隔"
                  value={filterKeywords}
                  onChange={(e) => setFilterKeywords(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg py-2 px-3 text-sm focus:ring-1 focus:ring-blue-500 outline-none"
                />
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <label className="text-sm font-medium text-slate-400 flex items-center space-x-2">
            <CommandLineIcon className="w-4 h-4" />
            <span>日志输出</span>
          </label>
          <button onClick={() => setLogs([])} className="text-xs text-slate-500 hover:text-slate-300">清空</button>
        </div>
        <div className="bg-slate-900 rounded-2xl border border-slate-800 p-4 h-64 overflow-auto font-mono text-xs space-y-1.5 shadow-inner">
          {logs.map((log, i) => (
            <div key={i} className="flex space-x-3 animate-in fade-in slide-in-from-left-2 duration-300">
              <span className="text-slate-600 shrink-0">[{log.timestamp}]</span>
              <span className={`font-semibold shrink-0 uppercase w-12 ${getLevelColor(log.level)}`}>{log.level}</span>
              <span className="text-slate-400 break-all">{log.message}</span>
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  );
}

function getLevelColor(level) {
  switch (level?.toLowerCase()) {
    case 'error': return 'text-rose-500';
    case 'warning': return 'text-amber-500';
    case 'success': return 'text-emerald-500';
    case 'debug': return 'text-slate-500';
    default: return 'text-blue-400';
  }
}
