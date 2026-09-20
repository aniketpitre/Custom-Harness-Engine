import { useEffect, useState } from 'react';

export const SessionDetail = ({ sessionId }: { sessionId: string }) => {
    const [events, setEvents] = useState<any[]>([]);
    const [msg, setMsg] = useState('');

    const handleInterrupt = () => {
        fetch(`http://localhost:8000/sessions/${sessionId}/interrupt`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message: msg })
        });
    }

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
            <input value={msg} onChange={e => setMsg(e.target.value)} placeholder="Interruption message" />
            <button onClick={handleInterrupt}>Interrupt</button>
            {events.map((e, index) => (
                <div key={index} style={{ border: '1px solid #ccc', margin: '5px', padding: '5px' }}>
                    <strong>{e.type}</strong>
                    <pre>{JSON.stringify(e, null, 2)}</pre>
                </div>
            ))}
        </div>
    );
};
