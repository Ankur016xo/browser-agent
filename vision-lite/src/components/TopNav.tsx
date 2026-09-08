import { Eye } from 'lucide-react';

interface TopNavProps {
  advancedMode: boolean;
  onToggleAdvanced: () => void;
}

export function TopNav({ advancedMode, onToggleAdvanced }: TopNavProps) {
  return (
    <header className="fixed top-0 left-0 right-0 z-50 h-14 flex items-center justify-between px-4 sm:px-6 bg-black/60 backdrop-blur-xl border-b border-white/[0.06]">
      <div className="flex items-center gap-2.5">
        <div className="relative w-7 h-7 flex items-center justify-center">
          <div className="absolute inset-0 rounded-full bg-gradient-to-br from-white/20 to-white/5 border border-white/20" />
          <Eye className="w-3.5 h-3.5 text-white relative z-10" strokeWidth={1.5} />
        </div>
        <span className="text-[15px] font-medium tracking-tight text-white">
          Vision <span className="font-serif italic text-ink-100">Lite</span>
        </span>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={onToggleAdvanced}
          className={`liquid-pill px-3.5 py-1.5 rounded-full text-xs font-medium tracking-wide transition-all ${
            advancedMode ? 'liquid-pill-active text-white' : 'text-ink-200'
          }`}
        >
          {advancedMode ? 'Advanced' : 'Simple'}
        </button>
        <div className="hidden sm:flex items-center gap-1.5 liquid-pill px-3 py-1.5 rounded-full">
          <div className="w-1.5 h-1.5 rounded-full bg-emerald-400/80" />
          <span className="text-xs text-ink-200 font-medium">Agent Online</span>
        </div>
      </div>
    </header>
  );
}
