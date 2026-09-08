import { useRef, useState, KeyboardEvent } from 'react';
import { Play, Pause, Square, RotateCcw } from 'lucide-react';
import type { AgentStatus } from '@/types/agent';

interface TaskInputProps {
  status: AgentStatus;
  onStart: (task: string) => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
}

export function TaskInput({ status, onStart, onPause, onResume, onStop }: TaskInputProps) {
  const [value, setValue] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const isRunning = ['WORKING', 'THINKING', 'VERIFYING', 'RECOVERING'].includes(status);
  const isPaused = status === 'PAUSED';
  const isDone = ['COMPLETED', 'FAILED', 'INCOMPLETE'].includes(status);
  const canStart = value.trim().length > 0 && !isRunning && !isPaused && !isSubmitting;

  function triggerStart() {
    if (!canStart || isSubmitting) return;
    setIsSubmitting(true);
    onStart(value.trim());
    setTimeout(() => setIsSubmitting(false), 800);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && canStart) {
      triggerStart();
    }
  }

  function handleStart() {
    triggerStart();
  }

  function handleClear() {
    setValue('');
    inputRef.current?.focus();
  }

  return (
    <div className="w-full">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-sm text-ink-200 font-medium">
          What should I do for you?
        </span>
      </div>
      <div className="glass-surface-strong rounded-2xl p-1.5 flex items-center gap-2 transition-all focus-within:border-white/25">
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Search Wikipedia and find the capital of India..."
          disabled={isRunning}
          className="flex-1 bg-transparent px-4 py-3 text-[15px] text-white placeholder:text-ink-300/60 outline-none disabled:opacity-50"
        />
        {value && !isRunning && (
          <button
            onClick={handleClear}
            className="liquid-pill px-2.5 py-2 rounded-xl text-xs text-ink-200 hover:text-white transition-colors"
          >
            Clear
          </button>
        )}
        {/* Control buttons */}
        <div className="flex items-center gap-1.5">
          {isRunning && (
            <>
              <button
                onClick={onPause}
                className="liquid-pill p-2.5 rounded-xl text-ink-100 hover:text-white transition-all group"
                title="Pause"
              >
                <Pause className="w-4 h-4" strokeWidth={1.5} />
              </button>
              <button
                onClick={onStop}
                className="liquid-pill p-2.5 rounded-xl text-ink-100 hover:text-white transition-all"
                title="Stop"
              >
                <Square className="w-4 h-4" strokeWidth={1.5} />
              </button>
            </>
          )}
          {isPaused && (
            <>
              <button
                onClick={onResume}
                className="liquid-pill p-2.5 rounded-xl text-ink-100 hover:text-white transition-all"
                title="Resume"
              >
                <Play className="w-4 h-4" strokeWidth={1.5} />
              </button>
              <button
                onClick={onStop}
                className="liquid-pill p-2.5 rounded-xl text-ink-100 hover:text-white transition-all"
                title="Stop"
              >
                <Square className="w-4 h-4" strokeWidth={1.5} />
              </button>
            </>
          )}
          {isDone && (
            <button
              onClick={handleClear}
              className="liquid-pill p-2.5 rounded-xl text-ink-100 hover:text-white transition-all"
              title="New task"
            >
              <RotateCcw className="w-4 h-4" strokeWidth={1.5} />
            </button>
          )}
          {!isRunning && !isPaused && !isDone && (
            <button
              onClick={handleStart}
              disabled={!canStart}
              className="liquid-pill px-5 py-2.5 rounded-xl text-sm font-medium text-white transition-all disabled:opacity-30 disabled:cursor-not-allowed hover:liquid-pill-active relative overflow-hidden group"
            >
              <span className="relative z-10 flex items-center gap-1.5">
                <Play className="w-3.5 h-3.5" strokeWidth={2} />
                Run
              </span>
              <span className="absolute inset-0 overflow-hidden rounded-xl">
                <span className="absolute top-0 -left-full w-full h-full bg-gradient-to-r from-transparent via-white/20 to-transparent group-hover:animate-shine" />
              </span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
