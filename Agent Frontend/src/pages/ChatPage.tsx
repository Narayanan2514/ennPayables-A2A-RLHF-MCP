import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { pipelineApi } from "../api/pipelineClient";
import { RunCard } from "../components/RunCard";
import { ChatTrack } from "../components/StepTrack";
import type { WorkflowMode, WorkflowRecord } from "../api/types";

export function ChatPage({ agentNames }: { agentNames: Record<string, string> }) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState<WorkflowMode>("auto");
  const [runs, setRuns] = useState<WorkflowRecord[]>([]);
  const queryClient = useQueryClient();

  const chat = useMutation({
    mutationFn: () => pipelineApi.chat(text, mode),
    onSuccess: (run) => {
      setRuns((prev) => [run, ...prev]);
      setText("");
      queryClient.invalidateQueries({ queryKey: ["history"] });
    },
  });

  return (
    <section>
      <div className="panel-header">
        <h2>Ad-hoc Agent Request</h2>
        <span className="muted">Client-side router selects the agent(s); each agent's own crew picks the tool</span>
      </div>
      <form
        className="chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) chat.mutate();
        }}
      >
        <textarea
          rows={2}
          placeholder="e.g. Poll the inbox now — or — Push this extracted invoice to the ERP: {...}"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="chat-controls">
          <select value={mode} onChange={(e) => setMode(e.target.value as WorkflowMode)}>
            <option value="auto">Mode: auto</option>
            <option value="sequential">Mode: sequential</option>
            <option value="parallel">Mode: parallel</option>
          </select>
          <button type="submit" className="btn btn-primary" disabled={chat.isPending}>
            {chat.isPending ? "Running…" : "Send"}
          </button>
        </div>
      </form>
      <div className="runs-list">
        {chat.isError && <p className="muted" style={{ color: "var(--accent-red)" }}>Request failed.</p>}
        {runs.map((run) => (
          <RunCard key={run.workflowId} run={run} agentNames={agentNames} track={<ChatTrack steps={run.steps} agentNames={agentNames} />} />
        ))}
      </div>
    </section>
  );
}
