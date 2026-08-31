import { useEffect, useState } from 'react'
import {
  formatApiError,
  getReview,
  submitDecisions,
  type ReviewCard,
  type ReviewPerson,
  type ReviewSubmitResult,
  type SpeakerDecisionInput,
} from '../api/client'
import { DecisionDraft, draftValid, SpeakerCard } from './SpeakerCard'

const UNKNOWN_KINDS = new Set(['KEEP_UNKNOWN', 'UNDECIDED_UNKNOWN'])

interface SpeakerReviewProps {
  meetingId: string
  onSubmitted: (result: ReviewSubmitResult) => void
}

function toDecision(clusterId: string, draft: DecisionDraft): SpeakerDecisionInput {
  const decision: SpeakerDecisionInput = { cluster_id: clusterId, kind: draft.kind }
  if (draft.kind === 'NEW_PERSON') {
    decision.display_name = (draft.display_name ?? '').trim()
  }
  if (draft.kind === 'MERGE_WITH_CLUSTER') {
    decision.merge_into_cluster_id = draft.merge_into_cluster_id
  }
  if (draft.kind === 'REASSIGN' || draft.kind === 'LINK_EXISTING') {
    decision.person_id = draft.person_id
  }
  return decision
}

export function SpeakerReview({ meetingId, onSubmitted }: SpeakerReviewProps) {
  const [cards, setCards] = useState<ReviewCard[] | null>(null)
  const [people, setPeople] = useState<ReviewPerson[]>([])
  const [drafts, setDrafts] = useState<Record<string, DecisionDraft>>({})
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let stale = false
    getReview(meetingId)
      .then((review) => {
        if (!stale) {
          setCards(review.cards)
          setPeople(review.people ?? [])
          // 「较高」建议默认选中「确认建议身份」；仍由用户过目并提交，可随时改选
          setDrafts((prev) => {
            const seeded = { ...prev }
            for (const card of review.cards) {
              if (
                seeded[card.cluster_id] === undefined &&
                card.suggested_person_id !== null &&
                card.suggested_tier === 'high'
              ) {
                seeded[card.cluster_id] = { kind: 'CONFIRM' }
              }
            }
            return seeded
          })
        }
      })
      .catch((e: unknown) => {
        if (!stale) {
          setError(formatApiError(e))
        }
      })
    return () => {
      stale = true
    }
  }, [meetingId])

  if (cards === null) {
    return (
      <section className="section">
        {error !== null ? (
          <div className="notice notice-error">{error}</div>
        ) : (
          <p className="section-desc">加载确认包…</p>
        )}
      </section>
    )
  }

  const allDecided = cards.every((card) => draftValid(drafts[card.cluster_id]))
  const undecidedIds = cards
    .filter((card) => !draftValid(drafts[card.cluster_id]))
    .map((card) => card.cluster_id)

  const batchSet = (kind: 'NEAREST_CONFIRMED' | 'UNDECIDED_UNKNOWN') => {
    setDrafts((prev) => ({
      ...prev,
      ...Object.fromEntries(undecidedIds.map((id) => [id, { kind }])),
    }))
  }
  const hasUnknown = cards.some((card) => {
    const draft = drafts[card.cluster_id]
    return draft !== undefined && UNKNOWN_KINDS.has(draft.kind)
  })

  const handleSubmit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const decisions = cards.map((card) => toDecision(card.cluster_id, drafts[card.cluster_id]))
      const result = await submitDecisions(meetingId, decisions)
      onSubmitted(result)
    } catch (e: unknown) {
      setError(formatApiError(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="section">
      <h2 className="section-title">说话人确认</h2>
      <p className="section-desc">
        为每位说话人试听片段并做一个决定；系统只提供建议，最终身份由你确认，「暂不确定」也是合法决定。
      </p>
      <div className="review-cards">
        {cards.map((card, index) => (
          <SpeakerCard
            key={card.cluster_id}
            meetingId={meetingId}
            card={card}
            otherClusterIds={cards
              .map((c) => c.cluster_id)
              .filter((clusterId) => clusterId !== card.cluster_id)}
            people={people}
            anonymousIndex={index + 1}
            clusterLabels={Object.fromEntries(
              cards.map((c, i) => [c.cluster_id, i + 1]),
            )}
            draft={drafts[card.cluster_id]}
            onChange={(draft) =>
              setDrafts((prev) => ({ ...prev, [card.cluster_id]: draft }))
            }
          />
        ))}
      </div>
      {undecidedIds.length >= 3 && (
        <div className="review-batch">
          <div className="review-batch-row">
            <span className="form-hint">其余 {undecidedIds.length} 张未决定：</span>
            <button type="button" className="btn" onClick={() => batchSet('NEAREST_CONFIRMED')}>
              并入已确认参会人（按声纹就近）
            </button>
            <button type="button" className="btn" onClick={() => batchSet('UNDECIDED_UNKNOWN')}>
              全部保持匿名
            </button>
          </div>
          <div className="review-batch-hint">
            就近归属按声纹相似度并入上面已确认的人；这些发言在转写与纪要中会标注（就近归属），且不进声纹库。
          </div>
        </div>
      )}
      <div className="review-footer">
        <button
          type="button"
          className="btn btn-primary"
          disabled={!allDecided || submitting}
          onClick={() => {
            void handleSubmit()
          }}
        >
          提交确认
        </button>
        {!allDecided && (
          <span className="form-hint">每张卡都需要一个决定后才能提交</span>
        )}
        {hasUnknown && (
          <span className="notice notice-warn">
            含未确认说话人：提交后纪要会带「含未确认说话人」标记
          </span>
        )}
      </div>
      {error !== null && (
        <div className="notice notice-error" style={{ marginTop: 10 }}>
          {error}
        </div>
      )}
    </section>
  )
}
