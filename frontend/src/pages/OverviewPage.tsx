import { useEffect, useState } from 'react';

export const Overview = () => {
    const [status, setStatus] = useState<any>(null);

    useEffect(() => {
        fetch('http://localhost:8000/api/status')
            .then(res => res.json())
            .then(data => setStatus(data));
    }, []);

    return (
        <div>
            <h2>Dashboard Overview</h2>
            {status && <pre>{JSON.stringify(status, null, 2)}</pre>}
        </div>
    );
};
