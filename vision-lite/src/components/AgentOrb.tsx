import type { AgentStatus } from '@/types/agent';

interface AgentOrbProps {
  status: AgentStatus;
  size?: number;
}

const statusConfig: Record<AgentStatus, { label: string; color: string; glow: string }> = {
  IDLE:       { label: 'Ready',       color: 'rgba(255,255,255,0.3)',  glow: '0 0 12px rgba(255,255,255,0.1)' },
  READY:      { label: 'Ready',       color: 'rgba(255,255,255,0.4)',  glow: '0 0 12px rgba(255,255,255,0.15)' },
  THINKING:   { label: 'Thinking',    color: 'rgba(216,216,216,0.6)',  glow: '0 0 16px rgba(216,216,216,0.25)' },
  WORKING:    { label: 'Working',     color: 'rgba(255,255,255,0.7)',  glow: '0 0 20px rgba(255,255,255,0.3)' },
  VERIFYING:  { label: 'Verifying',   color: 'rgba(200,220,255,0.6)',  glow: '0 0 16px rgba(200,220,255,0.25)' },
  RECOVERING: { label: 'Recovering',  color: 'rgba(255,200,150,0.5)',  glow: '0 0 16px rgba(255,200,150,0.25)' },
  COMPLETED:  { label: 'Completed',   color: 'rgba(180,255,200,0.6)',  glow: '0 0 20px rgba(180,255,200,0.3)' },
  FAILED:     { label: 'Failed',      color: 'rgba(255,150,150,0.5)',  glow: '0 0 16px rgba(255,150,150,0.25)' },
  INCOMPLETE: { label: 'Incomplete',  color: 'rgba(255,200,150,0.4)',  glow: '0 0 12px rgba(255,200,150,0.2)' },
  PAUSED:     { label: 'Paused',      color: 'rgba(154,154,154,0.4)',  glow: '0 0 8px rgba(154,154,154,0.15)' },
};

export function AgentOrb({ status, size = 56 }: AgentOrbProps) {
  const cfg = statusConfig[status];
  const isActive = ['WORKING', 'THINKING', 'VERIFYING', 'RECOVERING'].includes(status);

  return (
    <div className="flex flex-col items-center gap-3">
      <div
        className="relative flex items-center justify-center"
        style={{ width: size, height: size }}
      >
        {/* Outer glow ring */}
        <div
          className="absolute inset-0 rounded-full transition-all duration-700"
          style={{
            background: `radial-gradient(circle, ${cfg.color} 0%, transparent 70%)`,
            filter: 'blur(8px)',
            opacity: isActive ? 0.8 : 0.4,
          }}
        />
        {/* Rotating ring */}
        {isActive && (
          <div
            className="absolute inset-0 rounded-full border border-white/10 animate-orb-rotate"
            style={{
              borderTopColor: cfg.color,
              borderRightColor: 'transparent',
              borderBottomColor: 'transparent',
              borderLeftColor: 'transparent',
            }}
          />
        )}
        {/* Core orb */}
        <div
          className={`relative rounded-full transition-all duration-500 ${isActive ? 'animate-orb-pulse' : ''}`}
          style={{
            width: size * 0.5,
            height: size * 0.5,
            background: `radial-gradient(circle at 35% 35%, rgba(255,255,255,0.9) 0%, ${cfg.color} 40%, rgba(40,40,42,0.8) 100%)`,
            boxShadow: cfg.glow,
          }}
        >
          {/* Inner highlight */}
          <div
            className="absolute rounded-full"
            style={{
              top: '15%',
              left: '20%',
              width: '30%',
              height: '30%',
              background: 'rgba(255,255,255,0.4)',
              filter: 'blur(4px)',
            }}
          />
        </div>
      </div>
      <span className="text-xs font-medium tracking-widest uppercase text-ink-200">
        {cfg.label}
      </span>
    </div>
  );
}
