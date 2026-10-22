import { useQuery } from "@tanstack/react-query";
import { pipelineApi } from "../api/pipelineClient";
import { RunCard } from "../components/RunCard";
import { PipelineTrack } from "../components/StepTrack";

export function PipelinePage({ agentNames }: { agentNames: Record<string, string> }) {
  const history = useQuery({
    queryKey: ["history", "email_pipeline"],
    queryFn: () => pipelineApi.history("email_pipeline", 50),
    refetchInterval: 2000,
  });

  const runs = history.data?.workflows ?? [];

  return (
    <section>
      <div className="panel-header">
        <h2>Email &rarr; ERP Pipeline Runs</h2>
        {/* <span className="muted">Auto-refreshing every 2s</span> */}
      </div>
      <div className="runs-list">
        {!runs.length && (
          <p className="muted">
            No pipeline runs yet. Emails found by Agent 1's background poller (or a manual &ldquo;Poll Inbox
            Now&rdquo;) will appear here as they move through validation, extraction, and the ERP push (JDE or EBS,
            per TARGET_ERP).
          </p>
        )}
        {runs.map((run) => (
          <RunCard key={run.workflowId} run={run} agentNames={agentNames} track={<PipelineTrack steps={run.steps} />} />
        ))}
      </div>
    </section>
  );
}
