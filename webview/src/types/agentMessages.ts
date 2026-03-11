export type AgentMessageType =
  | 'thought'
  | 'permission_request'
  | 'permission_response'
  | 'file_edit'
  | 'final_answer';

export interface AgentWireMessage {
  sender: string;
  msg_type: AgentMessageType;
  content: string;
  meta: Record<string, unknown>;
}

export interface FinalAnswerMessage extends AgentWireMessage {
  msg_type: 'final_answer';
}

export type ChatRole = 'user' | 'assistant';

export interface ChatBubble {
  id: string;
  role: ChatRole;
  content: string;
  timestamp: string;
  meta?: Record<string, unknown>;
}

export const isAgentWireMessage = (value: unknown): value is AgentWireMessage => {
  if (!value || typeof value !== 'object') {
    return false;
  }

  const candidate = value as Partial<AgentWireMessage>;
  const meta = candidate.meta ?? {};
  return (
    typeof candidate.sender === 'string' &&
    typeof candidate.msg_type === 'string' &&
    typeof candidate.content === 'string' &&
    typeof meta === 'object' &&
    meta !== null
  );
};

export const isFinalAnswerMessage = (value: unknown): value is FinalAnswerMessage => {
  return isAgentWireMessage(value) && value.msg_type === 'final_answer';
};
