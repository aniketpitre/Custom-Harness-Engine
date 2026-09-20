import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/shell/Layout';
import { OverviewPage } from './pages/OverviewPage';
import { CommandPalette } from "./components/CommandPalette";
import { RunsPage } from './pages/RunsPage';
import { LiveRunPage } from './pages/LiveRunPage';
import { AnalyticsPage } from './pages/AnalyticsPage';

function App() {
  return (
    <BrowserRouter>
    <CommandPalette />
      <Layout>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/run/:sessionId" element={<LiveRunPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
