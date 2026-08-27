import { useEffect, useState } from 'react'
import {
  deleteVoiceprint,
  formatApiError,
  listVoiceprints,
  type Voiceprint,
} from '../api/client'
import { Icon } from '../components/Icon'

export function VoiceprintsPage() {
  const [voiceprints, setVoiceprints] = useState<Voiceprint[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  useEffect(() => {
    let stale = false
    listVoiceprints()
      .then((items) => {
        if (!stale) {
          setVoiceprints(items)
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
  }, [])

  const onDelete = (voiceprintId: string) => {
    setDeletingId(voiceprintId)
    setError(null)
    deleteVoiceprint(voiceprintId)
      .then(() => {
        setVoiceprints((current) =>
          current === null ? current : current.filter((item) => item.id !== voiceprintId),
        )
      })
      .catch((e: unknown) => {
        setError(formatApiError(e))
      })
      .finally(() => {
        setDeletingId(null)
      })
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">声纹库</h1>
          <p className="page-subtitle">
            确认说话人时自动入库；删除后不再据此建议该人身份
          </p>
        </div>
      </div>

      {error !== null && <div className="notice notice-error">{error}</div>}

      {voiceprints !== null && (
        <div className="list-card">
          {voiceprints.length === 0 ? (
            <div className="empty">
              <div className="empty-title">声纹库是空的</div>
              <div>在会议确认环节确认说话人身份后，合格片段会自动生成声纹</div>
            </div>
          ) : (
            voiceprints.map((voiceprint) => (
              <div key={voiceprint.id} className="list-row">
                <span className="list-row-title">{voiceprint.display_name}</span>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={deletingId === voiceprint.id}
                  onClick={() => onDelete(voiceprint.id)}
                  aria-label={`删除 ${voiceprint.display_name} 的声纹`}
                >
                  <Icon name="trash" size={12} />
                  删除
                </button>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
