import type { AgentService } from '@/types/agent';
import { createHttpAgentService } from './httpAgentService';

// Connect directly to the Python backend
const backendUrl = import.meta.env.VITE_AGENT_BACKEND_URL as string | undefined;

export const agentService: AgentService = createHttpAgentService(backendUrl);
