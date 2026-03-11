import React, { FormEvent, startTransition, useEffect, useRef, useState } from 'react';

import { ChatBubble, isAgentWireMessage } from '../types/agentMessages';

const WS_URL = 'ws://127.0.0.1:8765/ws?client_id=vscode-gui';
const MAX_RECONNECT_DELAY_MS = 10000;

type ConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'disconnected';

const makeId = () =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

const formatClock = (isoTimestamp: string) =>
  new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(isoTimestamp));

const connectionLabelMap: Record<ConnectionState, string> = {
  connecting: 'Connecting to local brain',
  connected: 'Connected',
  reconnecting: 'Reconnecting',
  disconnected: 'Disconnected',
};

const connectionToneMap: Record<ConnectionState, string> = {
  connecting: 'text-[var(--vscode-charts-yellow)]',
  connected: 'text-[var(--vscode-testing-iconPassed)]',
  reconnecting: 'text-[var(--vscode-charts-blue)]',
  disconnected: 'text-[var(--vscode-errorForeground)]',
};

export function ChatPanel(): React.ReactElement {
  const [messages, setMessages] = useState<ChatBubble[]>([]);
  const [draft, setDraft] = useState('');
  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting');
  const [retryCount, setRetryCount] = useState(0);

  const websocketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const manualCloseRef = useRef(false);
  const messageListRef = useRef<HTMLDivElement | null>(null);
  const pendingEchoesRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    const list = messageListRef.current;
    if (!list) {
      return;
    }

    list.scrollTop = list.scrollHeight;
  }, [messages]);

  useEffect(() => {
    manualCloseRef.current = false;

    const connect = (attempt: number) => {
      if (manualCloseRef.current) {
        return;
      }

      setConnectionState(attempt === 0 ? 'connecting' : 'reconnecting');
      const websocket = new WebSocket(WS_URL);
      websocketRef.current = websocket;

      websocket.onopen = () => {
        setConnectionState('connected');
        setRetryCount(0);
      };

      websocket.onmessage = (event) => {
        let parsed: unknown;

        try {
          parsed = JSON.parse(String(event.data));
        } catch {
          return;
        }

        if (!isAgentWireMessage(parsed)) {
          return;
        }

        if (
          parsed.msg_type === 'thought' ||
          parsed.msg_type === 'permission_request' ||
          parsed.msg_type === 'file_edit'
        ) {
          return;
        }

        if (parsed.sender === 'user') {
          const pendingCount = pendingEchoesRef.current.get(parsed.content) ?? 0;
          if (pendingCount > 0) {
            if (pendingCount === 1) {
              pendingEchoesRef.current.delete(parsed.content);
            } else {
              pendingEchoesRef.current.set(parsed.content, pendingCount - 1);
            }
            return;
          }

          startTransition(() => {
            setMessages((current) => [
              ...current,
              {
                id: makeId(),
                role: 'user',
                content: parsed.content,
                timestamp: new Date().toISOString(),
                meta: parsed.meta,
              },
            ]);
          });
          return;
        }

        if (parsed.msg_type === 'final_answer') {
          startTransition(() => {
            setMessages((current) => [
              ...current,
              {
                id: makeId(),
                role: 'assistant',
                content: parsed.content,
                timestamp: new Date().toISOString(),
                meta: parsed.meta,
              },
            ]);
          });
        }
      };

      websocket.onerror = () => {
        websocket.close();
      };

      websocket.onclose = () => {
        websocketRef.current = null;

        if (manualCloseRef.current) {
          setConnectionState('disconnected');
          return;
        }

        const nextAttempt = attempt + 1;
        const delay = Math.min(1000 * 2 ** attempt, MAX_RECONNECT_DELAY_MS);
        setConnectionState('reconnecting');
        setRetryCount(nextAttempt);

        if (reconnectTimerRef.current !== null) {
          window.clearTimeout(reconnectTimerRef.current);
        }

        reconnectTimerRef.current = window.setTimeout(() => connect(nextAttempt), delay);
      };
    };

    connect(0);

    return () => {
      manualCloseRef.current = true;

      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
      }

      websocketRef.current?.close();
      websocketRef.current = null;
    };
  }, []);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const prompt = draft.trim();
    if (!prompt) {
      return;
    }

    const websocket = websocketRef.current;
    if (!websocket || websocket.readyState !== WebSocket.OPEN) {
      return;
    }

    const pendingCount = pendingEchoesRef.current.get(prompt) ?? 0;
    pendingEchoesRef.current.set(prompt, pendingCount + 1);

    websocket.send(
      JSON.stringify({
        sender: 'user',
        msg_type: 'thought',
        content: prompt,
      }),
    );

    startTransition(() => {
      setMessages((current) => [
        ...current,
        {
          id: makeId(),
          role: 'user',
          content: prompt,
          timestamp: new Date().toISOString(),
        },
      ]);
      setDraft('');
    });
  };

  const isConnected = connectionState === 'connected';

  return (
    <section className="flex h-full min-h-0 flex-col bg-[var(--vscode-sideBar-background)] text-[var(--vscode-editor-foreground)]">
      <header className="border-b border-[var(--vscode-panel-border)] px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--vscode-descriptionForeground)]">
              Agent Sidebar
            </p>
            <h1 className="truncate text-sm font-semibold text-[var(--vscode-foreground)]">Headless IDE Assistant</h1>
          </div>
          <span
            className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${connectionToneMap[connectionState]}`}
            style={{
              borderColor: 'var(--vscode-panel-border)',
              backgroundColor: 'var(--vscode-editor-background)',
            }}
          >
            {connectionLabelMap[connectionState]}
          </span>
        </div>
        <p className="mt-2 text-xs leading-5 text-[var(--vscode-descriptionForeground)]">
          Front-of-house mode: only your own messages and the backend&apos;s <code>final_answer</code> are shown here.
        </p>
      </header>

      <div ref={messageListRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.length === 0 ? (
          <div
            className="rounded-2xl border border-dashed p-4 text-sm leading-6"
            style={{
              borderColor: 'var(--vscode-panel-border)',
              backgroundColor: 'var(--vscode-editor-background)',
              color: 'var(--vscode-descriptionForeground)',
            }}
          >
            Send a prompt to the local brain. Internal thoughts, approval packets, and file edits stay hidden.
          </div>
        ) : (
          messages.map((message) => {
            const isUser = message.role === 'user';

            return (
              <article
                key={message.id}
                className={`max-w-[92%] rounded-2xl border px-3 py-3 shadow-sm ${isUser ? 'ml-auto' : 'mr-auto'}`}
                style={{
                  borderColor: isUser
                    ? 'var(--vscode-button-background)'
                    : 'var(--vscode-panel-border)',
                  backgroundColor: isUser
                    ? 'var(--vscode-button-background)'
                    : 'var(--vscode-editor-background)',
                  color: isUser
                    ? 'var(--vscode-button-foreground)'
                    : 'var(--vscode-editor-foreground)',
                }}
              >
                <div className="mb-2 flex items-center justify-between gap-3 text-[11px] uppercase tracking-[0.18em] opacity-75">
                  <span>{isUser ? 'You' : 'Assistant'}</span>
                  <span>{formatClock(message.timestamp)}</span>
                </div>
                <p className="whitespace-pre-wrap break-words text-sm leading-6">{message.content}</p>
              </article>
            );
          })
        )}
      </div>

      <footer className="border-t border-[var(--vscode-panel-border)] bg-[var(--vscode-editor-background)] px-4 py-4">
        <form className="space-y-3" onSubmit={handleSubmit}>
          <textarea
            className="min-h-[104px] w-full resize-none rounded-xl border px-3 py-3 text-sm leading-6 outline-none transition focus:ring-1"
            style={{
              borderColor: 'var(--vscode-input-border, var(--vscode-panel-border))',
              backgroundColor: 'var(--vscode-input-background)',
              color: 'var(--vscode-input-foreground)',
              boxShadow: 'none',
            }}
            placeholder="Ask the local agent brain to work. Only the final answer will come back here."
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />

          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-[var(--vscode-descriptionForeground)]">
              {isConnected ? 'Connected to ws://127.0.0.1:8765/ws' : `Socket retry attempt ${retryCount}`}
            </p>
            <button
              type="submit"
              disabled={!draft.trim() || !isConnected}
              className="rounded-lg px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60"
              style={{
                backgroundColor: 'var(--vscode-button-background)',
                color: 'var(--vscode-button-foreground)',
              }}
            >
              Send
            </button>
          </div>
        </form>
      </footer>
    </section>
  );
}

export default ChatPanel;
