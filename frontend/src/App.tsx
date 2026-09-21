import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/shell/Layout';
import { CommandPalette } from "./components/CommandPalette";
import { OverviewPage } from './pages/OverviewPage';
import { RunsPage } from './pages/RunsPage';
import { LiveRunPage } from './pages/LiveRunPage';
import { AnalyticsPage } from './pages/AnalyticsPage';
import { SettingsPage } from './pages/SettingsPage';
import { SkillsPage } from './pages/SkillsPage';
import { ApprovalsPage } from './pages/ApprovalsPage';
import { OrchestrationPage } from './pages/OrchestrationPage';
import { VerificationPage } from './pages/VerificationPage';

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
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/skills" element={<SkillsPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/orchestration" element={<OrchestrationPage />} />
          <Route path="/verification" element={<VerificationPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
