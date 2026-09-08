import type {
  AgentEvent,
  AgentState,
  AgentService,
  EventType,
  Procedure,
  TimelineEntry,
  VerificationResult,
} from '@/types/agent';

// ── Helpers ──────────────────────────────────────────────

function now(): number {
  return Date.now();
}

function ts(t: number): string {
  const d = new Date(t);
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  const s = String(d.getSeconds()).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

let idCounter = 0;
function uid(prefix: string): string {
  idCounter += 1;
  return `${prefix}_${idCounter}`;
}

// ── Mock scenario ────────────────────────────────────────
// Simulates: "Go to Wikipedia, open the India article, find the capital of India."

interface Step {
  status: AgentState['status'];
  actionLabel: string;          // user-facing current action
  timelineMsg: string;           // timeline entry
  eventType: EventType;
  url: string;
  title: string;
  screenshot: string;
  procedureUpdate?: { index: number; status: Procedure['status'] };
  verification?: VerificationResult;
  result?: string;
  advancedDelta?: Partial<AgentState['advanced']>;
  delay: number; // ms before this step fires
}

const WIKI_SCREENSHOT =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800" viewBox="0 0 1280 800">
  <rect width="1280" height="800" fill="#1a1a1d"/>
  <rect x="0" y="0" width="1280" height="56" fill="#0a0a0b"/>
  <circle cx="28" cy="28" r="8" fill="#ff5f57"/>
  <circle cx="52" cy="28" r="8" fill="#febc2e"/>
  <circle cx="76" cy="28" r="8" fill="#28c840"/>
  <rect x="120" y="16" width="500" height="24" rx="6" fill="#28282A"/>
  <text x="136" y="33" font-family="Inter,sans-serif" font-size="13" fill="#9A9A9A">en.wikipedia.org</text>
  <text x="120" y="120" font-family="Georgia,serif" font-size="42" fill="#D8D8D8">India</text>
  <rect x="120" y="150" width="600" height="3" fill="#28282A"/>
  <text x="120" y="200" font-family="Inter,sans-serif" font-size="16" fill="#9A9A9A">India (Bharat), officially the Republic of India, is a country in South Asia.</text>
  <text x="120" y="230" font-family="Inter,sans-serif" font-size="16" fill="#9A9A9A">It is the seventh-largest country by area and the most populous democracy.</text>
  <rect x="120" y="270" width="120" height="32" rx="6" fill="#1c1c1f" stroke="#3a3a3d"/>
  <text x="132" y="290" font-family="Inter,sans-serif" font-size="13" fill="#D8D8D8">History</text>
  <rect x="260" y="270" width="120" height="32" rx="6" fill="#1c1c1f" stroke="#3a3a3d"/>
  <text x="272" y="290" font-family="Inter,sans-serif" font-size="13" fill="#D8D8D8">Geography</text>
  <rect x="400" y="270" width="130" height="32" rx="6" fill="#1c1c1f" stroke="#3a3a3d"/>
  <text x="412" y="290" font-family="Inter,sans-serif" font-size="13" fill="#D8D8D8">Demographics</text>
  <text x="120" y="350" font-family="Inter,sans-serif" font-size="16" fill="#9A9A9A">Capital: New Delhi</text>
  <text x="120" y="380" font-family="Inter,sans-serif" font-size="16" fill="#9A9A9A">Largest city: Mumbai (by population)</text>
  <text x="120" y="450" font-family="Inter,sans-serif" font-size="14" fill="#5a5a5e">Coordinates: 21°N 78°E</text>
</svg>
`);

const WIKI_HISTORY_SCREENSHOT =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800" viewBox="0 0 1280 800">
  <rect width="1280" height="800" fill="#1a1a1d"/>
  <rect x="0" y="0" width="1280" height="56" fill="#0a0a0b"/>
  <circle cx="28" cy="28" r="8" fill="#ff5f57"/>
  <circle cx="52" cy="28" r="8" fill="#febc2e"/>
  <circle cx="76" cy="28" r="8" fill="#28c840"/>
  <rect x="120" y="16" width="500" height="24" rx="6" fill="#28282A"/>
  <text x="136" y="33" font-family="Inter,sans-serif" font-size="13" fill="#9A9A9A">en.wikipedia.org/wiki/History_of_India</text>
  <text x="120" y="120" font-family="Georgia,serif" font-size="36" fill="#D8D8D8">History of India</text>
  <rect x="120" y="150" width="600" height="3" fill="#28282A"/>
  <text x="120" y="200" font-family="Inter,sans-serif" font-size="16" fill="#9A9A9A">The history of India spans thousands of years...</text>
  <text x="120" y="230" font-family="Inter,sans-serif" font-size="16" fill="#9A9A9A">From the Indus Valley Civilization to modern times.</text>
</svg>
`);

const SEARCH_SCREENSHOT =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800" viewBox="0 0 1280 800">
  <rect width="1280" height="800" fill="#0a0a0b"/>
  <rect x="440" y="200" width="400" height="48" rx="24" fill="#1c1c1f" stroke="#3a3a3d"/>
  <text x="460" y="230" font-family="Inter,sans-serif" font-size="16" fill="#D8D8D8">India</text>
  <circle cx="810" cy="224" r="10" fill="none" stroke="#9A9A9A" stroke-width="2"/>
  <text x="500" y="310" font-family="Inter,sans-serif" font-size="14" fill="#9A9A9A">India - Wikipedia</text>
  <text x="500" y="340" font-family="Inter,sans-serif" font-size="14" fill="#9A9A9A">India (Bharat) - Wikipedia, the free encyclopedia</text>
  <text x="500" y="370" font-family="Inter,sans-serif" font-size="14" fill="#5a5a5e">en.wikipedia.org › wiki › India</text>
</svg>
`);

const BLANK_SCREENSHOT =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800" viewBox="0 0 1280 800">
  <rect width="1280" height="800" fill="#0a0a0b"/>
  <rect x="0" y="0" width="1280" height="56" fill="#050505"/>
  <circle cx="28" cy="28" r="8" fill="#ff5f57"/>
  <circle cx="52" cy="28" r="8" fill="#febc2e"/>
  <circle cx="76" cy="28" r="8" fill="#28c840"/>
  <rect x="120" y="16" width="500" height="24" rx="6" fill="#141416"/>
  <text x="136" y="33" font-family="Inter,sans-serif" font-size="13" fill="#5a5a5e">about:blank</text>
</svg>
`);

function buildScenario(task: string): Step[] {
  return [
    {
      status: 'WORKING',
      actionLabel: 'Opening Wikipedia.',
      timelineMsg: 'Opened Wikipedia',
      eventType: 'ACTION_STARTED',
      url: 'https://en.wikipedia.org',
      title: 'Wikipedia',
      screenshot: WIKI_SCREENSHOT,
      delay: 800,
      advancedDelta: { url: 'https://en.wikipedia.org', domElements: 342, somElements: 18 },
    },
    {
      status: 'WORKING',
      actionLabel: 'Searching for India.',
      timelineMsg: 'Searched for India',
      eventType: 'ACTION_COMPLETED',
      url: 'https://en.wikipedia.org/w/index.php?search=India',
      title: 'Search results - Wikipedia',
      screenshot: SEARCH_SCREENSHOT,
      delay: 1200,
      verification: { passed: true, message: 'Search results appeared' },
      advancedDelta: { domElements: 218, somElements: 12 },
    },
    {
      status: 'WORKING',
      actionLabel: 'I found the India article.',
      timelineMsg: 'Opened India article',
      eventType: 'ACTION_COMPLETED',
      url: 'https://en.wikipedia.org/wiki/India',
      title: 'India - Wikipedia',
      screenshot: WIKI_SCREENSHOT,
      procedureUpdate: { index: 0, status: 'completed' },
      delay: 1200,
      verification: { passed: true, message: 'Page changed to India article' },
      advancedDelta: { domElements: 487, somElements: 24 },
    },
    {
      status: 'WORKING',
      actionLabel: "I'm looking for the requested section.",
      timelineMsg: 'Scanning article for capital',
      eventType: 'OBSERVATION',
      url: 'https://en.wikipedia.org/wiki/India',
      title: 'India - Wikipedia',
      screenshot: WIKI_SCREENSHOT,
      delay: 1000,
      advancedDelta: { confidence: 0.94 },
    },
    {
      status: 'VERIFYING',
      actionLabel: 'Checking the result.',
      timelineMsg: 'Verified capital information',
      eventType: 'VERIFICATION_COMPLETED',
      url: 'https://en.wikipedia.org/wiki/India',
      title: 'India - Wikipedia',
      screenshot: WIKI_SCREENSHOT,
      procedureUpdate: { index: 1, status: 'completed' },
      delay: 1000,
      verification: { passed: true, message: 'Requirement satisfied' },
      advancedDelta: { confidence: 0.97 },
    },
    {
      status: 'COMPLETED',
      actionLabel: 'Task completed.',
      timelineMsg: 'Task completed',
      eventType: 'TASK_COMPLETED',
      url: 'https://en.wikipedia.org/wiki/India',
      title: 'India - Wikipedia',
      screenshot: WIKI_SCREENSHOT,
      procedureUpdate: { index: 2, status: 'completed' },
      delay: 600,
      verification: { passed: true, message: 'Requirement satisfied' },
      result: 'The capital of India is New Delhi.',
      advancedDelta: { confidence: 0.98 },
    },
  ];
}

// ── Mock Agent Service ────────────────────────────────────

export function createMockAgentService(): AgentService {
  let state: AgentState = createInitialState();
  let eventHandlers: ((e: AgentEvent) => void)[] = [];
  let stateHandlers: ((s: AgentState) => void)[] = [];
  let timeoutHandle: ReturnType<typeof setTimeout> | null = null;
  let stepIndex = 0;
  let steps: Step[] = [];
  let running = false;

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

  function emitEvent(type: EventType, message: string, data?: Record<string, unknown>) {
    const event: AgentEvent = { type, timestamp: now(), message, data };
    for (const h of eventHandlers) h(event);
  }

  function notifyState() {
    for (const h of stateHandlers) h({ ...state });
  }

  function addLog(message: string, type: TimelineEntry['type']) {
    const entry: TimelineEntry = {
      id: uid('log'),
      timestamp: now(),
      message,
      type,
    };
    state.logs = [...state.logs, entry];
    state.advanced.rawLogs = [
      ...state.advanced.rawLogs,
      `[${ts(entry.timestamp)}] ${type.toUpperCase()}: ${message}`,
    ];
  }

  function runNextStep() {
    if (!running || stepIndex >= steps.length) return;

    const step = steps[stepIndex];
    timeoutHandle = setTimeout(() => {
      state = { ...state };

      state.status = step.status;
      state.currentAction = step.actionLabel;
      state.url = step.url;
      state.title = step.title;
      state.screenshot = step.screenshot;
      state.step = stepIndex + 1;

      if (step.verification) {
        state.verification = step.verification;
      }
      if (step.result) {
        state.result = step.result;
      }
      if (step.advancedDelta) {
        state.advanced = { ...state.advanced, ...step.advancedDelta };
        state.advanced.url = step.url;
        state.advanced.title = step.title;
      }

      if (step.procedureUpdate) {
        const procs = [...state.procedures];
        if (procs[step.procedureUpdate.index]) {
          procs[step.procedureUpdate.index] = {
            ...procs[step.procedureUpdate.index],
            status: step.procedureUpdate.status,
          };
        }
        state.procedures = procs;
        state.completedProcedures = procs.filter((p) => p.status === 'completed').length;
        state.procedureIndex = step.procedureUpdate.index + 1;
      }

      addLog(step.timelineMsg, step.eventType.includes('VERIFICATION') ? 'verification' : 'action');

      emitEvent(step.eventType, step.timelineMsg);
      notifyState();

      stepIndex += 1;
      runNextStep();
    }, step.delay);
  }

  function startTask(task: string): void {
    if (running) return;
    state = { ...createInitialState() };
    state.task = task;
    state.status = 'THINKING';
    state.startedAt = now();
    state.screenshot = BLANK_SCREENSHOT;
    state.procedures = [
      { id: uid('proc'), label: 'Open India article', status: 'pending' },
      { id: uid('proc'), label: 'Find capital of India', status: 'pending' },
      { id: uid('proc'), label: 'Verify result', status: 'pending' },
    ];
    state.currentProcedure = state.procedures[0].label;

    steps = buildScenario(task);
    stepIndex = 0;
    running = true;

    addLog('Task started', 'system');
    emitEvent('TASK_STARTED', 'Task started');
    notifyState();

    // Brief thinking pause, then start running steps
    timeoutHandle = setTimeout(() => {
      state = { ...state, status: 'WORKING' };
      notifyState();
      runNextStep();
    }, 600);
  }

  function pause(): void {
    if (!running) return;
    running = false;
    if (timeoutHandle) clearTimeout(timeoutHandle);
    state = { ...state, status: 'PAUSED' };
    addLog('Agent paused', 'system');
    emitEvent('TASK_PAUSED', 'Agent paused');
    notifyState();
  }

  function resume(): void {
    if (running || state.status !== 'PAUSED') return;
    running = true;
    state = { ...state, status: 'WORKING' };
    addLog('Agent resumed', 'system');
    emitEvent('TASK_RESUMED', 'Agent resumed');
    notifyState();
    runNextStep();
  }

  function stop(): void {
    running = false;
    if (timeoutHandle) clearTimeout(timeoutHandle);
    if (state.status !== 'COMPLETED' && state.status !== 'FAILED') {
      state = { ...state, status: 'INCOMPLETE', result: state.result || 'Task was stopped before completion.' };
      addLog('Task stopped', 'system');
      emitEvent('TASK_INCOMPLETE', 'Task stopped');
      notifyState();
    }
  }

  function getState(): AgentState {
    return { ...state };
  }

  function subscribeToEvents(handler: (e: AgentEvent) => void): () => void {
    eventHandlers = [...eventHandlers, handler];
    return () => {
      eventHandlers = eventHandlers.filter((h) => h !== handler);
    };
  }

  function subscribeToState(handler: (s: AgentState) => void): () => void {
    stateHandlers = [...stateHandlers, handler];
    return () => {
      stateHandlers = stateHandlers.filter((h) => h !== handler);
    };
  }

  return {
    startTask,
    pause,
    resume,
    stop,
    getState,
    subscribeToEvents,
    subscribeToState,
  };
}
