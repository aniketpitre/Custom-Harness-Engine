import { useEffect, useState } from 'react';
import { SessionDetail } from './SessionDetail';

export const SessionList = () => {
    const [sessions, setSessions] = useState<any[]>([]);
    const [selectedId, setSelectedId] = useState<string | null>(null);

    useEffect(() => {
        fetch('http://localhost:8000/sessions')
            .then(res => res.json())
            .then(data => setSessions(data))
            .catch(err => console.error(err));
    }, []);

    return (
        <div>
            <h2>Active Sessions</h2>
            <ul>
                {sessions.map((s: any) => (
                    <li key={s.session_id} onClick={() => setSelectedId(s.session_id)}>
                        {s.goal} - {s.status}
                    </li>
                ))}
            </ul>
            {selectedId && <SessionDetail sessionId={selectedId} />}
        </div>
    );
};
