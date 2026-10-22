export function AgentCardModal({
  title,
  card,
  onClose,
}: {
  title: string;
  card: Record<string, unknown>;
  onClose: () => void;
}) {
  return (
    <div className="modal">
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal-body">
        <div className="modal-header">
          <h3>{title}</h3>
          <button className="btn btn-ghost" onClick={onClose}>
            &times;
          </button>
        </div>
        <pre id="agent-card-json">{JSON.stringify(card, null, 2)}</pre>
      </div>
    </div>
  );
}
