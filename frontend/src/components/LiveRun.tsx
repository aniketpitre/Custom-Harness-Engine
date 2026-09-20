import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';

export const LiveRun = () => {
    const { sessionId } = useParams<{ sessionId: string }>();
    const [events, setEvents] = useState<any[]>([]);
    const endRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const eventSource = new EventSource(`http://localhost:8000/sessions/${sessionId}/stream`);
        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            setEvents((prev) => [...prev, data]);
            endRef.current?.scrollIntoView({ behavior: 'smooth' });
        };
        return () => eventSource.close();
    }, [sessionId]);

    return (
        <div className="bg-black p-4 h-[600px] overflow-y-auto font-mono text-xs text-green-400 border border-slate-700 rounded shadow-inner">
            {events.map((e, i) => (
                <div key={i}>
                   <span className="text-slate-500">[{new Date().toLocaleTimeString()}]</span> {JSON.stringify(e)}
                </div>
            ))}
            <div ref={endRef} />
        </div>
    );
};
