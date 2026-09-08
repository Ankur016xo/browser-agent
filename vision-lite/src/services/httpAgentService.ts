import type {
  AgentEvent,
  AgentService,
  AgentState,
} from '@/types/agent';

// ── HTTP-based adapter for the real Vision Lite backend ──
//
// Connects to the Browser Agent Python backend runtime:
//   - POST /api/task/start   { task }  → starts the agent
//   - POST /api/task/pause              → pauses
//   - POST /api/task/resume             → resumes
//   - POST /api/task/stop               → stops
//   - GET  /api/task/state              → returns current AgentState
//   - SSE  /api/task/events             → streams Server-Sent Events

const DEFAULT_BASE =
  typeof window !== 'undefined' && window.location && window.location.origin && window.location.origin.startsWith('http')
    ? window.location.origin
    : 'http://127.0.0.1:8787';

function createInitialState(): AgentState {
  return {
    status: 'IDLE',
    task: '',
    step: 0,
    maxSteps: 30,
    url: '',
    title: '',
    screenshot: null,
    currentAction: '',
    currentProcedure: '',
    procedureIndex: 0,
    procedures: [],
    completedProcedures: 0,
    verification: null,
    result: null,
    extractedData: null,
    finalState: '',
    logs: [],
    advanced: {
      url: '',
      title: '',
      domElements: 0,
      somElements: 0,
      model: 'qwen2.5-vl:3b',
      confidence: 0,
      actionJson: null,
      loopDetected: false,
      recoveryEvents: 0,
      rawLogs: [],
    },
    startedAt: null,
  };
}

export function createHttpAgentService(baseUrl?: string): AgentService {
  const rawBase = baseUrl || DEFAULT_BASE;
  const base = rawBase.replace(/\/$/, '');

  let eventSource: EventSource | null = null;
  let eventHandlers: ((e: AgentEvent) => void)[] = [];
  let stateHandlers: ((s: AgentState) => void)[] = [];
  let cachedState: AgentState = createInitialState();

  function notifyState(s: AgentState) {
    cachedState = s;
    for (const h of stateHandlers) {
      try {
        h(s);
      } catch (err) {
        console.error('Error in state handler:', err);
      }
    }
  }

  async function fetchState(): Promise<AgentState> {
    try {
      const res = await fetch(`${base}/api/task/state`, { cache: 'no-store' });
      if (res.ok) {
        return (await res.json()) as AgentState;
      }
    } catch {
      // fallback to legacy /api/state or /api/status if needed
    }

    const fallbackRes = await fetch(`${base}/api/state`, { cache: 'no-store' });
    if (!fallbackRes.ok) {
      throw new Error(`State fetch failed with status: ${fallbackRes.status}`);
    }
    return (await fallbackRes.json()) as AgentState;
  }

  function connectSSE() {
    if (eventSource || typeof EventSource === 'undefined') return;

    try {
      eventSource = new EventSource(`${base}/api/task/events`);

      eventSource.addEventListener('observation', (ev) => {
        try {
          const data = JSON.parse(ev.data);
          const evt: AgentEvent = {
            type: 'OBSERVATION',
            timestamp: Date.now(),
            message: data.message || `Navigated to ${data.url || 'page'}`,
            data,
          };
          for (const h of eventHandlers) h(evt);
        } catch {
          // ignore malformed
        }
      });

      eventSource.addEventListener('procedure_completed', (ev) => {
        try {
          const data = JSON.parse(ev.data);
          const evt: AgentEvent = {
            type: 'PROCEDURE_COMPLETED',
            timestamp: Date.now(),
            message: data.message || `Step ${data.step} completed`,
            data,
          };
          for (const h of eventHandlers) h(evt);
        } catch {
          // ignore malformed
        }
      });

      eventSource.addEventListener('task_completed', (ev) => {
        try {
          const data = JSON.parse(ev.data);
          const evt: AgentEvent = {
            type: 'TASK_COMPLETED',
            timestamp: Date.now(),
            message: data.summary || 'Task completed successfully',
            data,
          };
          for (const h of eventHandlers) h(evt);
        } catch {
          // ignore malformed
        }
      });

      eventSource.addEventListener('task_failed', (ev) => {
        try {
          const data = JSON.parse(ev.data);
          const evt: AgentEvent = {
            type: 'TASK_FAILED',
            timestamp: Date.now(),
            message: data.summary || 'Task stopped or encountered an error',
            data,
          };
          for (const h of eventHandlers) h(evt);
        } catch {
          // ignore malformed
        }
      });

      eventSource.onerror = () => {
        // SSE disconnected, close and let polling maintain state
        eventSource?.close();
        eventSource = null;
      };
    } catch {
      eventSource = null;
    }
  }

  return {
    startTask(task: string) {
      connectSSE();
      fetch(`${base}/api/task/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task }),
      })
        .catch(() => {
          return fetch(`${base}/api/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task }),
          });
        })
        .then(() => fetchState())
        .then((s) => notifyState(s))
        .catch((err) => console.warn('Start task error:', err));
    },

    pause() {
      fetch(`${base}/api/task/pause`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        .catch(() => fetch(`${base}/api/pause`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }))
        .then(() => fetchState())
        .then((s) => notifyState(s))
        .catch(() => {});
    },

    resume() {
      fetch(`${base}/api/task/resume`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        .catch(() => fetch(`${base}/api/resume`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }))
        .then(() => fetchState())
        .then((s) => notifyState(s))
        .catch(() => {});
    },

    stop() {
      fetch(`${base}/api/task/stop`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        .catch(() => fetch(`${base}/api/stop`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }))
        .then(() => fetchState())
        .then((s) => notifyState(s))
        .catch(() => {});
    },

    getState() {
      return cachedState;
    },

    subscribeToEvents(handler) {
      eventHandlers = [...eventHandlers, handler];
      connectSSE();
      return () => {
        eventHandlers = eventHandlers.filter((h) => h !== handler);
      };
    },

    subscribeToState(handler) {
      stateHandlers = [...stateHandlers, handler];

      // Fetch immediately on subscription
      fetchState()
        .then((s) => notifyState(s))
        .catch(() => {});

      // Poll state every 1s
      const interval = setInterval(async () => {
        try {
          const s = await fetchState();
          notifyState(s);
        } catch {
          // Backend offline or restarting
        }
      }, 1000);

      return () => {
        stateHandlers = stateHandlers.filter((h) => h !== handler);
        clearInterval(interval);
      };
    },
  };
}
