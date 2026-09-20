import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { useParams } from 'react-router';

export function LiveRunPage() {
  const { sessionId } = useParams();
  const termRef = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal | null>(null);

  useEffect(() => {
    if (!termRef.current) return;

    const term = new Terminal({
      cursorBlink: true,
      theme: { background: '#000000', foreground: '#f0e6d2' }
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(termRef.current);
    fitAddon.fit();
    terminal.current = term;

    // Connect to SSE stream
    const eventSource = new EventSource(`/api/sessions/${sessionId}/stream`);
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      term.writeln(`[${data.type}] ${data.content || JSON.stringify(data)}`);
    };

    return () => {
      eventSource.close();
      term.dispose();
    };
  }, [sessionId]);

  return (
    <div className="h-full w-full p-4">
      <div ref={termRef} className="h-full w-full rounded-lg border border-gray-800" />
    </div>
  );
}
