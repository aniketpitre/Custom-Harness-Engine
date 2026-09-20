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
            {events.map((e, index) => (
                <div key={index} style={{ border: '1px solid #ccc', margin: '5px', padding: '5px' }}>
                    <strong>{e.type}</strong>
                    {e.receipt?.verification?.passed === false && <span style={{ color: 'red' }}> [Risk: ALERT]</span>}
                    {e.type === 'tool_result' && <span>Tier: {e.policy_tier || 'N/A'}</span>}
                    <pre>{JSON.stringify(e, null, 2)}</pre>
                </div>
            ))}
        </div>
    );
};
