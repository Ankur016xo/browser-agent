// Core domain types for Vision Lite

export type AgentStatus =
  | 'IDLE'
  | 'READY'
  | 'THINKING'
  | 'WORKING'
  | 'VERIFYING'
  | 'RECOVERING'
  | 'COMPLETED'
  | 'FAILED'
  | 'INCOMPLETE'
  | 'PAUSED';

export type EventType =
  | 'TASK_STARTED'
  | 'OBSERVATION'
  | 'ACTION_STARTED'
  | 'ACTION_COMPLETED'
  | 'ACTION_FAILED'
  | 'VERIFICATION_STARTED'
  | 'VERIFICATION_COMPLETED'
  | 'PROCEDURE_COMPLETED'
  | 'RECOVERY_STARTED'
  | 'TASK_COMPLETED'
  | 'TASK_FAILED'
  | 'TASK_INCOMPLETE'
  | 'TASK_PAUSED'
  | 'TASK_RESUMED';

export interface Procedure {
  id: string;
  label: string;
  status: 'pending' | 'active' | 'completed' | 'failed';
}

export interface VerificationResult {
  passed: boolean;
  message: string;
}

export interface AgentEvent {
  type: EventType;
  timestamp: number;
  message: string;
  data?: Record<string, unknown>;
}

export interface TimelineEntry {
  id: string;
  timestamp: number;
  message: string;
  type: 'action' | 'verification' | 'recovery' | 'system';
}

export interface AdvancedInfo {
  url: string;
  title: string;
  domElements: number;
  somElements: number;
  model: string;
  confidence: number;
  actionJson: string | null;
  loopDetected: boolean;
  recoveryEvents: number;
  rawLogs: string[];
}

export interface AgentState {
  status: AgentStatus;
  task: string;
  step: number;
  maxSteps: number;
  url: string;
  title: string;
  screenshot: string | null;
  currentAction: string;
  currentProcedure: string;
  procedureIndex: number;
  procedures: Procedure[];
  completedProcedures: number;
  verification: VerificationResult | null;
  result: string | null;
  extractedData?: Record<string, any> | null;
  finalState?: string;
  logs: TimelineEntry[];
  advanced: AdvancedInfo;
  startedAt: number | null;
}

export interface AgentService {
  startTask(task: string): void;
  pause(): void;
  resume(): void;
  stop(): void;
  getState(): AgentState;
  subscribeToEvents(handler: (event: AgentEvent) => void): () => void;
  subscribeToState(handler: (state: AgentState) => void): () => void;
}
