import { useEffect, useState } from 'react';

export const Runs = () => {
    const [runs, setRuns] = useState([]);
    useEffect(() => {
        fetch('http://localhost:8000/api/runs')
            .then(res => res.json())
            .then(data => setRuns(data))
    }, []);

    return (
        <div>
            <h2>Recent Runs</h2>
            <pre>{JSON.stringify(runs, null, 2)}</pre>
        </div>
    );
};
