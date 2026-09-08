import { useEffect, useRef, useState, useCallback } from 'react';
import type { AgentState, AgentEvent } from '@/types/agent';
import { agentService } from '@/services/agentService';

const initialState: AgentState = agentService.getState();

export function useAgent() {
  const [state, setState] = useState<AgentState>(initialState);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const stateRef = useRef<AgentState>(initialState);

  useEffect(() => {
    const unsubState = agentService.subscribeToState((s) => {
      stateRef.current = s;
      setState(s);
    });
    const unsubEvents = agentService.subscribeToEvents((e) => {
      setEvents((prev) => [...prev, e]);
    });
    return () => {
      unsubState();
      unsubEvents();
    };
  }, []);

  const startTask = useCallback((task: string) => {
    setEvents([]);
    agentService.startTask(task);
  }, []);

  const pause = useCallback(() => agentService.pause(), []);
  const resume = useCallback(() => agentService.resume(), []);
  const stop = useCallback(() => agentService.stop(), []);

  return { state, events, startTask, pause, resume, stop };
}
