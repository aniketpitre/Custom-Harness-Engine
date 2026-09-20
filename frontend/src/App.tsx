import { Layout } from './components/shell/Layout';
import { Overview } from './components/Overview';
import { CommandPalette } from './components/CommandPalette';

function App() {
  return (
    <Layout>
      <CommandPalette />
      <Overview />
    </Layout>
  );
}
export default App;
