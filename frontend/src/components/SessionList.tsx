import { useEffect, useState } from 'react';

export const SessionList = () => {
    const [sessions, setSessions] = useState([]);

    useEffect(() => {
        // NOTE: Harness API might need explicit handling if list endpoint is different
        // Assuming GET /sessions returns a list
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
                    <li key={s.session_id}>
                        {s.goal} - {s.status}
                    </li>
                ))}
            </ul>
        </div>
    );
};
