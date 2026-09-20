import { useState } from 'react';

export const MemoryDreams = () => {
    const [dreams, setDreams] = useState([]);
    
    const fetchDreams = () => {
        fetch('http://localhost:8000/memory/dream', {method: 'POST'})
            .then(res => res.json())
            .then(data => setDreams(data.consolidated_themes))
            .catch(err => console.error(err));
    }

    return (
        <div>
            <button onClick={fetchDreams}>Trigger Memory Dream</button>
            <pre>{JSON.stringify(dreams, null, 2)}</pre>
        </div>
    );
};
