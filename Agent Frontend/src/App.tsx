import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { pipelineApi } from "./api/pipelineClient";
import { AgentCardModal } from "./components/AgentCardModal";
import { PipelinePage } from "./pages/PipelinePage";
import { ChatPage } from "./pages/ChatPage";
import { ExceptionsPage } from "./pages/ExceptionsPage";
import { ExceptionDetailPage } from "./pages/ExceptionDetailPage";
import { SessionsPage } from "./pages/SessionsPage";

export default function App() {
  const [openAgentId, setOpenAgentId] = useState<string | null>(null);

  const health = useQuery({
    queryKey: ["pipeline-health"],
    queryFn: pipelineApi.health,
    refetchInterval: 5000,
    retry: false,
  });

  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: pipelineApi.agents,
    refetchInterval: 15000,
  });

  const config = useQuery({ queryKey: ["pipeline-config"], queryFn: pipelineApi.config });

  const agentCard = useQuery({
    queryKey: ["agent-card", openAgentId],
    queryFn: () => pipelineApi.agentCard(openAgentId as string),
    enabled: openAgentId !== null,
  });

  const connected = !health.isError && health.data?.status === "ok";

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">A2A</span>
          <div>
            <h1>ennVault Agent Console</h1>
            <p className="subtitle">Email &rarr; ERP invoice pipeline, plus RLHF-assisted exception handling</p>
          </div>
        </div>
        <div className="header-actions">
          <span className={`status-pill ${connected ? "status-ok" : "status-error"}`}>
            <span className="dot" />
            {connected ? "orchestrator connected" : "orchestrator unreachable"}
          </span>
          <button className="btn btn-ghost" onClick={() => agents.refetch()}>
            Refresh Agents
          </button>
          <button
            className="btn btn-primary"
            disabled={agents.isLoading}
            onClick={async () => {
              await pipelineApi.pollNow();
            }}
          >
            Poll Inbox Now
          </button>
        </div>
      </header>

      <div className="layout">
        <aside className="agents-panel">
          <h2>Discovered Agents</h2>
          <div className="agents-list">
            {!agents.data?.agents.length && <p className="muted">No agents discovered yet.</p>}
            {agents.data?.agents.map((a) => (
              <div key={a.agentId} className="agent-card" onClick={() => setOpenAgentId(a.agentId)}>
                <div className="agent-card-top">
                  <div>
                    <div className="agent-card-name">{a.name}</div>
                    <div className="agent-card-meta">
                      {a.baseUrl} &middot; {a.skillCount} skill(s)
                    </div>
                  </div>
                  <span className={`agent-badge ${a.status === "available" ? "available" : "unavailable"}`}>
                    {a.status}
                  </span>
                </div>
              </div>
            ))}
            {agents.data?.errors && Object.keys(agents.data.errors).length > 0 && (
              <p className="muted" style={{ marginTop: 10, color: "var(--accent-red)" }}>
                {Object.keys(agents.data.errors).length} agent(s) unreachable during discovery.
              </p>
            )}
          </div>
          {/* <div className="watcher-info">
            <h3>Background schedules</h3>
            <dl>
              <dt>Mailbox poll</dt>
              <dd>every {config.data?.emailPollIntervalSeconds ?? "—"}s (Agent 1)</dd>
              <dt>Pipeline watcher</dt>
              <dd>every {config.data?.pipelineWatchIntervalSeconds ?? "—"}s (orchestrator)</dd>
            </dl>
          </div> */}
        </aside>

        <main className="content">
          <nav className="tabs">
            <NavLink to="/" end className={({ isActive }) => `tab-btn ${isActive ? "active" : ""}`}>
              Live Pipeline
            </NavLink>
            {/* <NavLink to="/chat" className={({ isActive }) => `tab-btn ${isActive ? "active" : ""}`}>
              Chat / Manual
            </NavLink> */}
            <NavLink to="/exceptions" className={({ isActive }) => `tab-btn ${isActive ? "active" : ""}`}>
              Exceptions
            </NavLink>
            <NavLink to="/sessions" className={({ isActive }) => `tab-btn ${isActive ? "active" : ""}`}>
              Sessions
            </NavLink>
          </nav>

          <Routes>
            <Route path="/" element={<PipelinePage agentNames={agentNameMap(agents.data?.agents)} />} />
            <Route path="/chat" element={<ChatPage agentNames={agentNameMap(agents.data?.agents)} />} />
            <Route path="/exceptions" element={<ExceptionsPage />} />
            <Route path="/exceptions/:srcId" element={<ExceptionDetailPage />} />
            <Route path="/sessions" element={<SessionsPage />} />
          </Routes>
        </main>
      </div>

      {openAgentId && agentCard.data && (
        <AgentCardModal
          title={(agentCard.data.name as string) || openAgentId}
          card={agentCard.data}
          onClose={() => setOpenAgentId(null)}
        />
      )}
    </div>
  );
}

function agentNameMap(agents: { agentId: string; name: string }[] | undefined): Record<string, string> {
  return Object.fromEntries((agents || []).map((a) => [a.agentId, a.name]));
}
