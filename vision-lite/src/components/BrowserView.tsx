import { Lock, Globe } from 'lucide-react';
import type { AgentState } from '@/types/agent';

interface BrowserViewProps {
  state: AgentState;
}

export function BrowserView({ state }: BrowserViewProps) {
  const hasScreenshot = !!state.screenshot;
  const domain = state.url ? (() => {
    try {
      return new URL(state.url).hostname;
    } catch {
      return state.url;
    }
  })() : '';

  return (
    <div className="glass-surface rounded-2xl overflow-hidden flex flex-col h-full">
      {/* Browser chrome */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-white/[0.06] bg-black/40">
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-white/15" />
          <div className="w-2.5 h-2.5 rounded-full bg-white/10" />
          <div className="w-2.5 h-2.5 rounded-full bg-white/[0.06]" />
        </div>
        <div className="flex-1 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.06] min-w-0">
          <Lock className="w-3 h-3 text-ink-300 flex-shrink-0" strokeWidth={1.5} />
          <span className="text-xs text-ink-200 truncate font-medium">
            {domain || 'about:blank'}
          </span>
        </div>
        {state.title && (
          <span className="hidden md:block text-xs text-ink-300 truncate max-w-[200px]">
            {state.title}
          </span>
        )}
      </div>

      {/* Viewport */}
      <div className="relative flex-1 bg-ink-900 overflow-hidden">
        {hasScreenshot ? (
          <div className="absolute inset-0 animate-fade-in">
            <img
              src={state.screenshot!}
              alt="Browser viewport"
              className="w-full h-full object-cover object-top"
            />
            {/* Subtle scan line when working */}
            {['WORKING', 'THINKING', 'VERIFYING', 'RECOVERING'].includes(state.status) && (
              <div className="absolute inset-0 pointer-events-none overflow-hidden">
                <div
                  className="absolute left-0 right-0 h-px bg-gradient-to-r from-transparent via-white/30 to-transparent animate-scan"
                  style={{ animationDuration: '2.5s' }}
                />
              </div>
            )}
            {/* Action indicator overlay */}
            {state.currentAction && ['WORKING', 'THINKING', 'VERIFYING', 'RECOVERING'].includes(state.status) && (
              <div className="absolute bottom-4 left-4 right-4 flex items-center gap-2 px-4 py-2.5 rounded-xl glass-surface-strong animate-fade-up">
                <div className="w-2 h-2 rounded-full bg-white/70 animate-orb-pulse" />
                <span className="text-sm text-white font-medium truncate">
                  {state.currentAction}
                </span>
              </div>
            )}
          </div>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="flex flex-col items-center gap-4 text-center px-8">
              <Globe className="w-10 h-10 text-ink-400" strokeWidth={1} />
              <div>
                <p className="text-sm text-ink-200 font-medium">Browser is ready</p>
                <p className="text-xs text-ink-300 mt-1">
                  Enter a task and the agent will start browsing
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
