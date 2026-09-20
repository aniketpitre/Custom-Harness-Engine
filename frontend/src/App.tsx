import { SessionList } from './components/SessionList';
import { MemoryDreams } from './components/MemoryDreams';
import './App.css';

function App() {
  return (
    <div className="App">
      <h1>Harness Engine Dashboard</h1>
      <MemoryDreams />
      <SessionList />
    </div>
  );
}

export default App;
