import React, { useState, useEffect } from 'react';
import { ChartBarIcon, DocumentCheckIcon, UserCircleIcon, CursorArrowRippleIcon, BoltIcon } from '@heroicons/react/24/outline';

const STAT_LABELS = {
  total_files: '总采集文件',
  total_records: '已收集记录',
  today_records: '今日新增数据',
};

export default function Dashboard() {
  const [stats, setStats] = useState({});
  const [trends, setTrends] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchStats = async () => {
    try {
      const resStats = await fetch(`http://${window.location.hostname}:8080/api/data/stats`);
      const resTrends = await fetch(`http://${window.location.hostname}:8080/api/data/stats/trends`);
      const dataStats = await resStats.json();
      const dataTrends = await resTrends.json();
      setStats(dataStats || {});
      setTrends(dataTrends.trends || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, []);

  if (loading) return <div className="p-8 text-center text-slate-500">正在同步实时大屏数据...</div>;

  return (
    <div className="p-8 space-y-10 animate-in fade-in duration-500">
      <div className="flex items-center space-x-4">
        <BoltIcon className="w-8 h-8 text-yellow-500" />
        <h2 className="text-3xl font-black tracking-tight">数据概览 Dashboard</h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
        <StatCard icon={DocumentCheckIcon} label="采集总量" value={stats.total_records || 0} color="text-blue-500" unit="条数据" />
        <StatCard icon={ChartBarIcon} label="成果文件" value={stats.total_files || 0} color="text-yellow-500" unit="个文件" />
        <StatCard icon={UserCircleIcon} label="活跃账号" value={2} color="text-emerald-500" unit="个已保持" />
        <StatCard icon={CursorArrowRippleIcon} label="历史爆发力" value={Math.max(...trends.map(t => t.count), 0)} color="text-rose-500" unit="最高日产量" />
      </div>

      <div className="bg-slate-900/50 border border-slate-800 p-8 rounded-3xl space-y-6">
        <h3 className="font-bold text-lg">最近 7 天采集趋势</h3>
        <div className="h-64 flex items-end justify-between space-x-2">
          {trends.map((t, i) => (
            <div key={i} className="flex-1 flex flex-col items-center group cursor-help">
              <div 
                className="w-full bg-blue-600/20 group-hover:bg-blue-600/40 border-t-2 border-blue-500 transition-all rounded-t-lg relative"
                style={{ height: `${(t.count / (Math.max(...trends.map(v => v.count), 1)) * 100)}%` }}
              >
                <div className="absolute -top-10 left-1/2 -translate-x-1/2 bg-slate-800 text-white text-[10px] py-1 px-2 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
                   {t.count} 条记录
                </div>
              </div>
              <span className="text-[10px] text-slate-500 mt-4 font-mono">{t.date.slice(5)}</span>
            </div>
          ))}
          {trends.length === 0 && <p className="text-slate-700 w-full text-center">暂无近期活跃记录</p>}
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, color, unit }) {
  return (
    <div className="bg-slate-900 border border-slate-800 p-6 rounded-3xl hover:border-slate-700 transition-all shadow-sm">
      <div className={`p-3 w-fit rounded-xl bg-slate-800 mb-4 ${color}`}>
        <Icon className="w-6 h-6" />
      </div>
      <p className="text-xs text-slate-500 font-bold uppercase tracking-widest">{label}</p>
      <div className="mt-2 flex items-baseline space-x-1">
        <span className="text-3xl font-black text-white lining-nums">{value}</span>
        <span className="text-xs text-slate-500">{unit}</span>
      </div>
    </div>
  );
}
