import { useEffect, useState } from 'react'
import {
  deleteVoiceprint,
  formatApiError,
  listVoiceprints,
  type Voiceprint,
  type VoiceprintLibrary,
} from '../api/client'
import { Icon } from '../components/Icon'
import { VoiceprintClip } from '../components/VoiceprintClip'

function formatEnrolledAt(value: string | null): string {
  if (value === null) {
    return '早期入库'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '早期入库'
  }
  return date.toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** 声纹库：按人分组的多模板列表，每条模板可试听、核对摘录、单独删除。 */
export function VoiceprintsPage() {
  const [library, setLibrary] = useState<VoiceprintLibrary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  useEffect(() => {
    let stale = false
    listVoiceprints()
      .then((data) => {
        if (!stale) {
          setLibrary(data)
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
        setLibrary((current) =>
          current === null
            ? current
            : {
                ...current,
                items: current.items.filter((item) => item.id !== voiceprintId),
              },
        )
      })
      .catch((e: unknown) => {
        setError(formatApiError(e))
      })
      .finally(() => {
        setDeletingId(null)
      })
  }

  // 以人员表为准分组：暂无模板的参会人也占一组，与确认页的人员口径保持一致。
  const groups: Array<{ personId: string; displayName: string; templates: Voiceprint[] }> = (
    library?.people ?? []
  ).map((person) => ({
    personId: person.id,
    displayName: person.display_name,
    templates: (library?.items ?? []).filter((item) => item.person_id === person.id),
  }))

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">声纹库</h1>
          <p className="page-subtitle">
            确认说话人时自动入库，每人保留 5 条不同环境的声纹模板；同场会只取最佳一条、同环境重复原地刷新、超出时自动淘汰最冗余的一条，也可随时试听后手动删除
          </p>
        </div>
      </div>

      {error !== null && <div className="notice notice-error">{error}</div>}

      {library !== null && (
        <div className="voiceprint-groups">
          {groups.length === 0 ? (
            <div className="list-card">
              <div className="empty">
                <div className="empty-title">声纹库是空的</div>
                <div>在会议确认环节确认说话人身份后，合格片段会自动生成声纹</div>
              </div>
            </div>
          ) : (
            groups.map((group) => (
              <div key={group.personId} className="list-card voiceprint-group">
                <div className="voiceprint-group-head">
                  <span className="list-row-title">{group.displayName}</span>
                  <span className="list-row-meta">
                    {group.templates.length > 0
                      ? `${group.templates.length} 条模板`
                      : '暂无模板'}
                  </span>
                </div>
                {group.templates.length === 0 && (
                  <div className="voiceprint-empty-note">
                    这位参会人还没有声纹模板，下次确认这个人的会议发言后会自动入库
                  </div>
                )}
                {group.templates.map((template) => (
                  <div key={template.id} className="list-row voiceprint-template">
                    {template.has_clip ? (
                      <VoiceprintClip
                        voiceprintId={template.id}
                        ownerName={group.displayName}
                      />
                    ) : (
                      <span className="clip-play voiceprint-no-clip" aria-hidden="true">
                        <Icon name="mic" size={10} />
                      </span>
                    )}
                    <span className="list-row-main">
                      <span className="voiceprint-snippet">
                        {template.snippet_text !== '' ? template.snippet_text : '（无转写摘录）'}
                      </span>
                      <span className="list-row-meta">
                        {template.source_meeting_title ?? '来源会议已不存在'} ·{' '}
                        {formatEnrolledAt(template.created_at)}
                        {!template.has_clip && ' · 无试听切片'}
                      </span>
                    </span>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      disabled={deletingId === template.id}
                      onClick={() => onDelete(template.id)}
                      aria-label={`删除 ${group.displayName} 的这条声纹模板`}
                    >
                      <Icon name="trash" size={12} />
                      删除
                    </button>
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
