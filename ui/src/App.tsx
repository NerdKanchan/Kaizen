import { HashRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ReviewerProvider } from "./lib/reviewer";
import { ToastProvider } from "./lib/toast";
import { LinkButton, PageHeader } from "./components/ui";
import ActionItemsPage from "./pages/ActionItemsPage";
import BusinessCasePage from "./pages/BusinessCasePage";
import DashboardPage from "./pages/DashboardPage";
import DiffPage from "./pages/DiffPage";
import DocumentPage from "./pages/DocumentPage";
import DocumentsPage from "./pages/DocumentsPage";
import EvidencePage from "./pages/EvidencePage";
import MiningPage from "./pages/MiningPage";
import LearningPage from "./pages/LearningPage";
import ReviewQueuePage from "./pages/ReviewQueuePage";
import AdminPage from "./pages/AdminPage";
import RunsPage from "./pages/RunsPage";
import TerminologyPage from "./pages/TerminologyPage";
import ProfilePage from "./pages/ProfilePage";

// HashRouter: the bundle is served as static files by the backend, so deep links must not need server routing.
export default function App() {
  return (
    <ReviewerProvider>
      <ToastProvider>
      <HashRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<RunsPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/runs/:runId" element={<DashboardPage />} />
            <Route path="/runs/:runId/review" element={<ReviewQueuePage />} />
            <Route path="/runs/:runId/rows/:rowId" element={<EvidencePage />} />
            <Route path="/runs/:runId/documents" element={<DocumentsPage />} />
            <Route path="/runs/:runId/documents/:docId" element={<DocumentPage />} />
            <Route path="/runs/:runId/mining" element={<MiningPage />} />
            <Route path="/runs/:runId/learning" element={<LearningPage />} />
            <Route path="/runs/:runId/business" element={<BusinessCasePage />} />
            <Route path="/runs/:runId/diff" element={<DiffPage />} />
            <Route path="/terminology" element={<TerminologyPage />} />
            <Route path="/action-items" element={<ActionItemsPage />} />
            <Route
              path="*"
              element={
                <div>
                  <PageHeader title="Page not found" description="The address doesn’t match a page in Kaizen." />
                  <LinkButton to="/" variant="primary">Back to runs</LinkButton>
                </div>
              }
            />
          </Route>
        </Routes>
      </HashRouter>
      </ToastProvider>
    </ReviewerProvider>
  );
}
