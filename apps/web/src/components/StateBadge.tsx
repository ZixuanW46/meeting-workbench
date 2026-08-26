import { stateLabel, stateTone } from '../labels'

export function StateBadge({ state }: { state: string }) {
  return (
    <span className={`badge badge-${stateTone(state)}`}>
      <span className="badge-dot" aria-hidden="true" />
      {stateLabel(state)}
    </span>
  )
}
