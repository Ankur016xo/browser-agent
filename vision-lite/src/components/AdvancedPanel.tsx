import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { AgentState } from '@/types/agent';

interface AdvancedPanelProps {
  state: AgentState;
}

function StatRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-white/[0.02] transition-colors">
      <span className="text-xs text-ink-300 font-medium">{label}</span>
      <span className="text-xs text-ink-100 font-mono tabular-nums">{value}</span>
    </div>
  );
}

export function AdvancedPanel({ state }: AdvancedPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const { advanced } = state;

  return (
    <div className="glass-surface rounded-2xl overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.02] transition-colors"
      >
        <span className="text-xs font-medium tracking-widest uppercase text-ink-200">
          Developer
        </span>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-ink-300" strokeWidth={1.5} />
        ) : (
          <ChevronDown className="w-4 h-4 text-ink-300" strokeWidth={1.5} />
        )}
      </button>

      {expanded && (
        <div className="px-3 pb-3 animate-fade-in space-y-1">
          <div className="border-t border-white/[0.04] pt-2 space-y-0.5">
            <StatRow label="Status" value={state.status} />
            <StatRow label="Step" value={`${state.step} / ${state.maxSteps}`} />
            <StatRow label="URL" value={advanced.url || '—'} />
            <StatRow label="Page Title" value={advanced.title || '—'} />
            <StatRow label="Model" value={advanced.model} />
            <StatRow label="Confidence" value={`${(advanced.confidence * 100).toFixed(0)}%`} />
            <StatRow label="DOM Elements" value={advanced.domElements} />
            <StatRow label="SOM Elements" value={advanced.somElements} />
            <StatRow label="Loop Detected" value={advanced.loopDetected ? 'true' : 'false'} />
            <StatRow label="Recovery Events" value={advanced.recoveryEvents} />
          </div>

          {advanced.actionJson && (
            <div className="mt-2 px-3 py-2 rounded-lg bg-black/40 border border-white/[0.04]">
              <p className="text-[10px] text-ink-300 uppercase tracking-wider mb-1">Action JSON</p>
              <pre className="text-[11px] text-ink-100 font-mono overflow-x-auto whitespace-pre-wrap break-all">
                {advanced.actionJson}
              </pre>
            </div>
          )}

          {state.verification && (
            <div className="mt-1 px-3 py-2 rounded-lg bg-black/40 border border-white/[0.04]">
              <p className="text-[10px] text-ink-300 uppercase tracking-wider mb-1">Verification</p>
              <p className="text-[11px] text-ink-100 font-mono">
                {state.verification.passed ? 'PASS' : 'FAIL'} — {state.verification.message}
              </p>
            </div>
          )}

          {advanced.rawLogs.length > 0 && (
            <div className="mt-1 px-3 py-2 rounded-lg bg-black/40 border border-white/[0.04] max-h-40 overflow-y-auto">
              <p className="text-[10px] text-ink-300 uppercase tracking-wider mb-1 sticky top-0">Raw Logs</p>
              <div className="space-y-0.5">
                {advanced.rawLogs.map((line, i) => (
                  <p key={i} className="text-[11px] text-ink-200 font-mono leading-relaxed">
                    {line}
                  </p>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
