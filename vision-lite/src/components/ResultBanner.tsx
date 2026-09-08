import { Check, X, Minus, Pause, Globe } from 'lucide-react';
import type { AgentState } from '@/types/agent';

interface ResultBannerProps {
  state: AgentState;
}

export function ResultBanner({ state }: ResultBannerProps) {
  const { status, result, verification, extractedData, url } = state;

  if (['IDLE', 'READY', 'THINKING', 'WORKING', 'VERIFYING', 'RECOVERING', 'PAUSED'].includes(status) && !result) {
    return null;
  }

  const isSuccess = status === 'COMPLETED';
  const isFailed = status === 'FAILED';
  const isIncomplete = status === 'INCOMPLETE';
  const isPaused = status === 'PAUSED';

  // Compute clean source domain
  const sourceName = (() => {
    if (!url) return '';
    try {
      const host = new URL(url).hostname.replace(/^www\./, '');
      if (host.includes('wikipedia')) return 'Wikipedia';
      if (host.includes('flipkart')) return 'Flipkart';
      if (host.includes('amazon')) return 'Amazon';
      return host;
    } catch {
      return '';
    }
  })();

  if (isPaused) {
    return (
      <div className="glass-surface-strong rounded-2xl p-5 animate-fade-up">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full glass-surface flex items-center justify-center">
            <Pause className="w-4 h-4 text-ink-100" strokeWidth={1.5} />
          </div>
          <div>
            <p className="text-sm font-medium text-white">Agent paused</p>
            <p className="text-xs text-ink-300 mt-0.5">Press resume to continue the task</p>
          </div>
        </div>
      </div>
    );
  }

  if (isSuccess) {
    // Extract recognized structured properties
    const data = extractedData || {};
    const capital = data.capital as string | undefined;
    const productName = (data.product_name || data.title) as string | undefined;
    const price = data.price as string | undefined;
    const rating = data.rating as string | undefined;
    const population = data.population as string | undefined;

    const hasStructuredCards = !!(capital || productName || price || rating || population);

    return (
      <div className="glass-surface-strong rounded-2xl p-5 sm:p-6 animate-fade-up border-white/20 shadow-2xl">
        <div className="flex items-center justify-between border-b border-white/[0.08] pb-3 mb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-full bg-emerald-500/20 border border-emerald-400/40 flex items-center justify-center flex-shrink-0 animate-scale-in">
              <Check className="w-3.5 h-3.5 text-emerald-300" strokeWidth={2.5} />
            </div>
            <div>
              <span className="text-xs uppercase tracking-widest text-emerald-400 font-semibold">
                Success
              </span>
              <h3 className="text-sm font-medium text-white">Task Completed</h3>
            </div>
          </div>
          {sourceName && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/[0.04] border border-white/[0.08]">
              <Globe className="w-3 h-3 text-ink-300" />
              <span className="text-xs text-ink-200 font-medium">{sourceName}</span>
            </div>
          )}
        </div>

        {/* Structured Result Cards */}
        {hasStructuredCards && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            {capital && (
              <div className="p-3 rounded-xl bg-white/[0.04] border border-white/[0.08]">
                <p className="text-[11px] uppercase tracking-wider text-ink-300 font-medium">Capital</p>
                <p className="text-base sm:text-lg font-medium text-white mt-0.5">{capital}</p>
              </div>
            )}
            {productName && (
              <div className="p-3 rounded-xl bg-white/[0.04] border border-white/[0.08] sm:col-span-2">
                <p className="text-[11px] uppercase tracking-wider text-ink-300 font-medium">Product</p>
                <p className="text-sm sm:text-base font-medium text-white mt-0.5 line-clamp-2">{productName}</p>
              </div>
            )}
            {price && (
              <div className="p-3 rounded-xl bg-white/[0.04] border border-white/[0.08]">
                <p className="text-[11px] uppercase tracking-wider text-ink-300 font-medium">Price</p>
                <p className="text-base sm:text-lg font-medium text-emerald-300 mt-0.5">{price}</p>
              </div>
            )}
            {rating && (
              <div className="p-3 rounded-xl bg-white/[0.04] border border-white/[0.08]">
                <p className="text-[11px] uppercase tracking-wider text-ink-300 font-medium">Rating</p>
                <p className="text-base sm:text-lg font-medium text-amber-300 mt-0.5 flex items-center gap-1">
                  {rating.includes('★') ? rating : `${rating} ★`}
                </p>
              </div>
            )}
            {population && (
              <div className="p-3 rounded-xl bg-white/[0.04] border border-white/[0.08]">
                <p className="text-[11px] uppercase tracking-wider text-ink-300 font-medium">Population</p>
                <p className="text-base sm:text-lg font-medium text-white mt-0.5">{population}</p>
              </div>
            )}
          </div>
        )}

        {/* Natural Language Summary */}
        {result && (
          <div className="px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.06] mb-3">
            <p className="text-xs text-ink-300 uppercase tracking-widest mb-1 font-medium">Summary</p>
            <p className="text-sm text-ink-100 leading-relaxed font-serif italic">{result}</p>
          </div>
        )}

        {/* Verification Footer */}
        <div className="flex items-center justify-between pt-2 text-xs text-ink-300">
          <span className="flex items-center gap-1.5 text-emerald-400/90 font-medium">
            <Check className="w-3.5 h-3.5" strokeWidth={2.5} />
            Verified
          </span>
          {verification?.message && (
            <span className="text-ink-300 text-[11px] truncate max-w-[280px]">
              {verification.message}
            </span>
          )}
        </div>
      </div>
    );
  }

  if (isFailed) {
    return (
      <div className="glass-surface-strong rounded-2xl p-5 sm:p-6 animate-fade-up border-red-500/30 shadow-2xl">
        <div className="flex items-center justify-between border-b border-red-500/20 pb-3 mb-3">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-full bg-red-500/20 border border-red-400/30 flex items-center justify-center flex-shrink-0">
              <X className="w-3.5 h-3.5 text-red-400" strokeWidth={2.5} />
            </div>
            <div>
              <span className="text-xs uppercase tracking-widest text-red-400 font-semibold">
                Task Not Completed
              </span>
              <h3 className="text-sm font-medium text-white">Honest Failure Reported</h3>
            </div>
          </div>
          {sourceName && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/[0.04] border border-white/[0.08]">
              <Globe className="w-3 h-3 text-ink-300" />
              <span className="text-xs text-ink-200 font-medium">{sourceName}</span>
            </div>
          )}
        </div>

        <div className="px-4 py-3 rounded-xl bg-red-500/[0.05] border border-red-500/10 mb-3">
          <p className="text-sm text-ink-100 leading-relaxed">
            {result || 'The requested information or target product could not be found within the specified constraints.'}
          </p>
        </div>

        <div className="flex items-center justify-between pt-1 text-xs text-ink-400">
          <span className="flex items-center gap-1.5 text-red-400">
            <X className="w-3 h-3" strokeWidth={2} />
            Unverified
          </span>
          <span className="text-[11px] text-ink-400">No hallucinated data produced</span>
        </div>
      </div>
    );
  }

  if (isIncomplete) {
    return (
      <div className="glass-surface-strong rounded-2xl p-5 animate-fade-up border-amber-500/30">
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 rounded-full bg-amber-500/10 border border-amber-400/30 flex items-center justify-center flex-shrink-0">
            <Minus className="w-4 h-4 text-amber-300" strokeWidth={2} />
          </div>
          <div>
            <span className="text-xs uppercase tracking-widest text-amber-400 font-medium">Incomplete</span>
            <p className="text-sm font-medium text-white mt-0.5">Task stopped before completion.</p>
            <p className="text-xs text-ink-300 mt-1">{result || 'The task was stopped or interrupted.'}</p>
          </div>
        </div>
      </div>
    );
  }

  return null;
}
