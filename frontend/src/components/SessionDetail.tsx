import { useEffect, useState } from 'react';

export const SessionDetail = ({ sessionId }: { sessionId: string }) => {
    const [events, setEvents] = useState<any[]>([]);

    useEffect(() => {
        const eventSource = new EventSource(`http://localhost:8000/sessions/${sessionId}/stream`);
        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            setEvents((prev) => [...prev, data]);
        };
        return () => eventSource.close();
    }, [sessionId]);

    return (
        <div>
            <h2>Stream: {sessionId}</h2>
            <pre>{JSON.stringify(events, null, 2)}</pre>
        </div>
    );
};
