import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import NotFound from "./pages/NotFound";
import Login from "./pages/Login";
import ModuleLayout from "./components/ModuleLayout";
import { Toaster as HotToaster } from "react-hot-toast";
import ChatbotWidget from "./components/ChatbotWidget";

// ennPayables (Oracle EBS) pages
import EBSDashboard from "./pages/ennPayables/EBS/InvoiceDashboard";
import EBSInboxPage from "./pages/ennPayables/EBS/InboxPage";
import EBSProcessedPage from "./pages/ennPayables/EBS/ProcessedPage";
import EBSExceptionsPage from "./pages/ennPayables/EBS/ExceptionsPage";
import EBSExceptionsPage_1 from "./pages/ennPayables/EBS/ExceptionsPage_1";
import EBSReportingPage from "./pages/ennPayables/EBS/ReportingPage";

const queryClient = new QueryClient();

const ebsConfig = {
  name: "ennPayables",
  shortName: "eP",
  subtitle: "Oracle EBS",
  basePath: "/ennPayables/EBS",
  accentClass: "text-success",
};

// Redirects to /login if no auth_token in localStorage
const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const isAuthenticated = !!localStorage.getItem("app_user");
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />;
};

// Shows the chat widget on every authenticated page, hidden on /login
const GlobalChatbot = () => {
  const location = useLocation();
  const isAuthenticated = !!localStorage.getItem("app_user");

  if (location.pathname === "/login" || !isAuthenticated) return null;

  return <ChatbotWidget />;
};

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <HotToaster position="top-right" />
      <BrowserRouter>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<Login />} />

          {/* Protected: home redirects straight into the ennPayables EBS module */}
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Navigate to="/ennPayables/EBS" replace />
              </ProtectedRoute>
            }
          />

          {/* ennPayables (EBS) */}
          <Route
            path="/ennPayables/EBS"
            element={
              <ProtectedRoute>
                <ModuleLayout
                  config={ebsConfig}
                  badges={{
                    Exceptions: { count: 5, variant: "bg-destructive text-destructive-foreground" },
                    Inbox: { count: 3, variant: "bg-success text-success-foreground" },
                  }}
                />
              </ProtectedRoute>
            }
          >
            <Route index element={<EBSDashboard />} />
            <Route path="inbox" element={<EBSInboxPage />} />
            <Route path="processed" element={<EBSProcessedPage />} />
            <Route path="exceptions" element={<EBSExceptionsPage />} />
            <Route path="exceptions_1" element={<EBSExceptionsPage_1 />} />
            <Route path="reporting" element={<EBSReportingPage />} />
          </Route>

          <Route path="*" element={<NotFound />} />
        </Routes>
        <GlobalChatbot />
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
