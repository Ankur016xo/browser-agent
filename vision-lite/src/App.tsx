import { useState } from 'react';
import { TopNav } from '@/components/TopNav';
import { AgentOrb } from '@/components/AgentOrb';
import { TaskInput } from '@/components/TaskInput';
import { BrowserView } from '@/components/BrowserView';
import { ProceduralProgress } from '@/components/ProceduralProgress';
import { ActionTimeline } from '@/components/ActionTimeline';
import { ResultBanner } from '@/components/ResultBanner';
import { AdvancedPanel } from '@/components/AdvancedPanel';
import { useAgent } from '@/hooks/useAgent';

function App() {
  const { state, startTask, pause, resume, stop } = useAgent();
  const [advancedMode, setAdvancedMode] = useState(false);

  const hasTask = state.status !== 'IDLE';
  const isRunning = ['WORKING', 'THINKING', 'VERIFYING', 'RECOVERING'].includes(state.status);

  return (
    <div className="min-h-screen bg-black text-white">
      {/* Ambient background glow */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div
          className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] rounded-full opacity-[0.04] blur-[120px]"
          style={{ background: 'radial-gradient(circle, white 0%, transparent 70%)' }}
        />
      </div>

      <TopNav advancedMode={advancedMode} onToggleAdvanced={() => setAdvancedMode(!advancedMode)} />

      <main className="relative pt-14 pb-8 px-4 sm:px-6 lg:px-8 min-h-screen">
        <div className="max-w-[1440px] mx-auto">
          {/* ── Hero / Task Input ─────────────────────────── */}
          <section className="pt-6 sm:pt-10 pb-6 animate-fade-down">
            <div className="flex flex-col items-center text-center mb-8">
              <AgentOrb status={state.status} size={64} />
              <h1 className="mt-6 text-3xl sm:text-4xl lg:text-5xl font-light tracking-tight text-white animate-fade-up">
                Your personal{' '}
                <span className="font-serif italic text-ink-100">browser agent</span>
              </h1>
              <p className="mt-2 text-sm text-ink-300 animate-fade-up" style={{ animationDelay: '0.1s' }}>
                Tell Vision Lite what to do. It will browse, act, and verify — for you.
              </p>
            </div>

            <div className="max-w-2xl mx-auto animate-fade-up" style={{ animationDelay: '0.15s' }}>
              <TaskInput
                status={state.status}
                onStart={startTask}
                onPause={pause}
                onResume={resume}
                onStop={stop}
              />
            </div>
          </section>

          {/* ── Workspace ────────────────────────────────── */}
          {hasTask && (
            <section className="grid grid-cols-1 lg:grid-cols-12 gap-4 animate-fade-in" style={{ animationDelay: '0.1s' }}>
              {/* Left column: Agent status + Progress */}
              <div className="lg:col-span-3 space-y-4 order-2 lg:order-1">
                {/* Agent status card */}
                <div className="glass-surface rounded-2xl p-5">
                  <div className="flex items-center gap-3">
                    <AgentOrb status={state.status} size={40} />
                    <div className="min-w-0">
                      <p className="text-xs text-ink-300 uppercase tracking-widest">Agent</p>
                      <p className="text-sm text-white font-medium truncate">
                        {isRunning ? 'Working on it...' : state.status === 'PAUSED' ? 'Paused' : state.status === 'COMPLETED' ? 'Done' : state.status}
                      </p>
                    </div>
                  </div>
                  {state.currentAction && (
                    <div className="mt-4 pt-4 border-t border-white/[0.06]">
                      <p className="text-xs text-ink-300 uppercase tracking-widest mb-1.5">Current Action</p>
                      <p className="text-sm text-ink-100 leading-snug">{state.currentAction}</p>
                    </div>
                  )}
                  {state.task && (
                    <div className="mt-4 pt-4 border-t border-white/[0.06]">
                      <p className="text-xs text-ink-300 uppercase tracking-widest mb-1.5">Task</p>
                      <p className="text-sm text-white leading-snug font-serif italic">"{state.task}"</p>
                    </div>
                  )}
                </div>

                {/* Procedural progress */}
                <ProceduralProgress
                  procedures={state.procedures}
                  currentIndex={state.procedureIndex}
                />

                {/* Verification badge */}
                {state.verification && (
                  <div className="glass-surface rounded-2xl p-4 animate-fade-up">
                    <p className="text-xs text-ink-300 uppercase tracking-widest mb-2">Verification</p>
                    <div className="flex items-center gap-2">
                      <div
                        className={`w-5 h-5 rounded-full flex items-center justify-center ${
                          state.verification.passed ? 'bg-white/10' : 'bg-red-500/10'
                        }`}
                      >
                        {state.verification.passed ? (
                          <svg viewBox="0 0 24 24" className="w-3 h-3 text-white" fill="none" stroke="currentColor" strokeWidth={3}>
                            <path d="M5 13l4 4L19 7" className="animate-check-stroke" style={{ strokeDasharray: 24, strokeDashoffset: 0 }} />
                          </svg>
                        ) : (
                          <span className="text-xs text-red-400">×</span>
                        )}
                      </div>
                      <span className="text-sm text-ink-100">{state.verification.message}</span>
                    </div>
                  </div>
                )}
              </div>

              {/* Center column: Browser workspace */}
              <div className="lg:col-span-6 order-1 lg:order-2 min-h-[400px] lg:min-h-[560px]">
                <BrowserView state={state} />
              </div>

              {/* Right column: Timeline + Advanced */}
              <div className="lg:col-span-3 space-y-4 order-3 min-h-0">
                <div className="h-[280px] lg:h-[420px]">
                  <ActionTimeline logs={state.logs} />
                </div>
                {advancedMode && <AdvancedPanel state={state} />}
              </div>
            </section>
          )}

          {/* ── Result ───────────────────────────────────── */}
          {hasTask && (
            <section className="mt-4 max-w-2xl mx-auto">
              <ResultBanner state={state} />
            </section>
          )}

          {/* ── Footer ───────────────────────────────────── */}
          <footer className="mt-12 pt-6 border-t border-white/[0.04] flex items-center justify-between">
            <p className="text-xs text-ink-300">
              Vision Lite — powered by Playwright, local vision models, and deterministic verification.
            </p>
            <p className="text-xs text-ink-400 hidden sm:block">
              Step {state.step} / {state.maxSteps}
            </p>
          </footer>
        </div>
      </main>
    </div>
  );
}

export default App;
