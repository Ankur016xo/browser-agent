import { Check, Loader2, Circle } from 'lucide-react';
import type { Procedure } from '@/types/agent';

interface ProceduralProgressProps {
  procedures: Procedure[];
  currentIndex: number;
}

export function ProceduralProgress({ procedures, currentIndex }: ProceduralProgressProps) {
  if (procedures.length === 0) return null;

  return (
    <div className="glass-surface rounded-2xl p-4 sm:p-5">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs font-medium tracking-widest uppercase text-ink-200">
          Progress
        </span>
        <span className="text-xs text-ink-300 tabular-nums">
          {procedures.filter((p) => p.status === 'completed').length} / {procedures.length}
        </span>
      </div>
      <div className="space-y-1">
        {procedures.map((proc, i) => {
          const isActive = i === currentIndex && proc.status !== 'completed';
          return (
            <div
              key={proc.id}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-300 ${
                isActive ? 'bg-white/[0.04]' : ''
              }`}
            >
              <div className="flex-shrink-0 w-5 h-5 flex items-center justify-center">
                {proc.status === 'completed' ? (
                  <div className="w-5 h-5 rounded-full bg-white/10 flex items-center justify-center animate-scale-in">
                    <Check className="w-3 h-3 text-white" strokeWidth={2.5} />
                  </div>
                ) : isActive ? (
                  <Loader2 className="w-4 h-4 text-ink-100 animate-spin" strokeWidth={1.5} />
                ) : (
                  <Circle className="w-4 h-4 text-ink-400" strokeWidth={1} />
                )}
              </div>
              <span
                className={`text-sm transition-colors duration-300 ${
                  proc.status === 'completed'
                    ? 'text-ink-200 line-through decoration-white/20'
                    : isActive
                    ? 'text-white font-medium'
                    : 'text-ink-300'
                }`}
              >
                {proc.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
