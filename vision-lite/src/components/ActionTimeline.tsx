import { useRef, useEffect } from 'react';
import { Check, X, Circle, Loader2 } from 'lucide-react';
import type { TimelineEntry } from '@/types/agent';

interface ActionTimelineProps {
  logs: TimelineEntry[];
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  const s = String(d.getSeconds()).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

export function ActionTimeline({ logs }: ActionTimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs.length]);

  return (
    <div className="glass-surface rounded-2xl p-4 sm:p-5 flex flex-col h-full min-h-0">
      <div className="flex items-center justify-between mb-3 border-b border-white/[0.04] pb-2">
        <span className="text-xs font-medium tracking-widest uppercase text-ink-200">
          Action Timeline
        </span>
        {logs.length > 0 && (
          <span className="text-xs text-ink-300 tabular-nums font-mono">{logs.length} events</span>
        )}
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto min-h-0 space-y-1.5 pr-1">
        {logs.length === 0 ? (
          <div className="flex items-center justify-center h-full min-h-[80px]">
            <p className="text-xs text-ink-300">No activity yet</p>
          </div>
        ) : (
          logs.map((entry) => {
            const raw = entry.message || '';
            const isCompleted = raw.startsWith('✓');
            const isActive = raw.startsWith('◉');
            const isFailed = raw.startsWith('✗');
            const cleanText = raw.replace(/^[✓◉✗]\s*/, '');

            return (
              <div
                key={entry.id}
                className={`flex items-start gap-2.5 px-2.5 py-1.5 rounded-lg transition-colors animate-slide-in ${
                  isActive ? 'bg-white/[0.04] border border-white/[0.08]' : 'hover:bg-white/[0.02]'
                }`}
              >
                <div className="mt-1 flex-shrink-0">
                  {isCompleted ? (
                    <div className="w-4 h-4 rounded-full bg-emerald-500/15 border border-emerald-400/30 flex items-center justify-center">
                      <Check className="w-2.5 h-2.5 text-emerald-300" strokeWidth={3} />
                    </div>
                  ) : isActive ? (
                    <div className="w-4 h-4 rounded-full bg-white/20 border border-white/40 flex items-center justify-center">
                      <div className="w-1.5 h-1.5 rounded-full bg-white animate-orb-pulse" />
                    </div>
                  ) : isFailed ? (
                    <div className="w-4 h-4 rounded-full bg-red-500/15 border border-red-400/30 flex items-center justify-center">
                      <X className="w-2.5 h-2.5 text-red-400" strokeWidth={3} />
                    </div>
                  ) : (
                    <Circle className="w-3.5 h-3.5 text-ink-400" strokeWidth={1.5} />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <span className={`text-xs sm:text-sm leading-snug break-words ${
                    isActive ? 'text-white font-medium' : isCompleted ? 'text-ink-100' : 'text-ink-200'
                  }`}>
                    {cleanText}
                  </span>
                </div>
                <span className="text-[10px] text-ink-400 tabular-nums font-mono mt-0.5 flex-shrink-0">
                  {formatTime(entry.timestamp)}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
