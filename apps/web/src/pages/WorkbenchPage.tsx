import { useCallback, useEffect, useRef, useState } from 'react'
import {
  formatApiError,
  getMeeting,
  reopenReview,
  updateMeetingTitle,
  type Meeting,
  type TranscriptVariant,
} from '../api/client'
import { ResultActionsMenu } from '../components/ResultActionsMenu'
import { DoctorBanner } from '../components/DoctorBanner'
import { Icon } from '../components/Icon'
import { Skeleton } from '../components/Skeleton'
import { toast } from '../components/Toast'
import { MinutesView } from '../components/MinutesView'
import { Progress } from '../components/Progress'
import { SpeakerReview } from '../components/SpeakerReview'
import { StateBadge } from '../components/StateBadge'
import { TranscriptView } from '../components/TranscriptView'
import { UploadPanel } from '../components/UploadPanel'

// UPLOADING 的进度由 tus 上传面板自己展示，不走 SSE 进度条
const PROGRESS_STATES = new Set([
  'QUEUED',
  'PROCESSING',
  'APPLYING_DECISIONS',
  'GENERATING_MINUTES',
])

const RESULT_STATES = new Set(['READY', 'PARTIAL_READY'])

export function WorkbenchPage({ meetingId }: { meetingId: string }) {
  const [meeting, setMeeting] = useState<Meeting | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  // 标题就地编辑：与词库注解同一套交互（Enter 保存 / Esc 取消）。
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [savingTitle, setSavingTitle] = useState(false)
  const meetingStateRef = useRef<string | null>(null)
  meetingStateRef.current = meeting?.state ?? null

  const refresh = useCallback(() => {
    getMeeting(meetingId)
      .then((data) => {
        // 纪要在后台生成完的那一次刷新，给个明确的完成反馈
        const previous = meetingStateRef.current
        if (previous !== null && previous !== 'READY' && data.state === 'READY') {
          toast('纪要已生成')
        }
        setMeeting(data)
        setError(null)
      })
      .catch((e: unknown) => setError(formatApiError(e)))
  }, [meetingId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const saveTitle = async () => {
    if (meeting === null) return
    const trimmed = titleDraft.trim()
    if (trimmed === '') return
    if (trimmed === meeting.title) {
      setEditingTitle(false)
      return
    }
    setSavingTitle(true)
    try {
      const updated = await updateMeetingTitle(meetingId, trimmed)
      setMeeting(updated)
      setEditingTitle(false)
      setError(null)
      toast('标题已更新')
    } catch (e: unknown) {
      setError(formatApiError(e))
    } finally {
      setSavingTitle(false)
    }
  }

  if (meeting === null) {
    return (
      <div className="page page-wide">
        <a className="back-link" href="#/">
          <Icon name="chevron-left" size={12} />
          返回会议列表
        </a>
        {error !== null ? (
          <div className="notice notice-error">{error}</div>
        ) : (
          <div data-testid="workbench-skeleton">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <Skeleton width="42%" height={22} />
              <Skeleton width={220} height={12} />
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="page page-wide">
      <a className="back-link" href="#/">
        <Icon name="chevron-left" size={12} />
        返回会议列表
      </a>
      <div className="page-header">
        <div style={{ flex: 1, minWidth: 0 }}>
          {editingTitle ? (
            <div className="title-edit-row">
              <input
                className="input input-title"
                aria-label="会议标题"
                value={titleDraft}
                maxLength={200}
                disabled={savingTitle}
                autoFocus
                onChange={(event) => setTitleDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    void saveTitle()
                  }
                  if (event.key === 'Escape') {
                    setEditingTitle(false)
                  }
                }}
              />
              <button
                type="button"
                className="btn"
                disabled={savingTitle || titleDraft.trim() === ''}
                onClick={() => {
                  void saveTitle()
                }}
              >
                保存
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={savingTitle}
                onClick={() => setEditingTitle(false)}
              >
                取消
              </button>
            </div>
          ) : (
            <div className="page-title-row">
              <h1 className="page-title">{meeting.title}</h1>
              <button
                type="button"
                className="btn btn-ghost title-edit-btn"
                aria-label="编辑标题"
                onClick={() => {
                  setTitleDraft(meeting.title)
                  setEditingTitle(true)
                }}
              >
                <Icon name="edit" size={13} />
              </button>
            </div>
          )}
          <div className="meta-row" style={{ marginTop: 4 }}>
            <StateBadge state={meeting.state} />
            {meeting.speakers.length + meeting.unknown_speaker_count > 0 && (
              <>
                <span className="divider-dot" />
                <span>
                  参会 {meeting.speakers.length + meeting.unknown_speaker_count} 人：
                  {meeting.speakers.join('、')}
                  {meeting.unknown_speaker_count > 0 &&
                    `${meeting.speakers.length > 0 ? '、' : ''}未知说话人 ×${meeting.unknown_speaker_count}`}
                </span>
              </>
            )}
            {meeting.hotwords.length > 0 && (
              <>
                <span className="divider-dot" />
                <span>热词：{meeting.hotwords.join('、')}</span>
              </>
            )}
          </div>
        </div>
      </div>

      <DoctorBanner />

      {error !== null && <div className="notice notice-error">{error}</div>}
      {notice !== null && (
        <div className="notice notice-warn" style={{ marginBottom: 12 }}>
          {notice}
        </div>
      )}

      {(meeting.state === 'DRAFT' || meeting.state === 'UPLOADING') && (
        <UploadPanel
          meetingId={meetingId}
          resuming={meeting.state === 'UPLOADING'}
          onUploaded={refresh}
        />
      )}

      {PROGRESS_STATES.has(meeting.state) && (
        <div className="card">
          <Progress
            meetingId={meetingId}
            onSnapshot={(snapshot) => {
              if (snapshot.state !== meetingStateRef.current) {
                refresh()
              }
            }}
          />
        </div>
      )}

      {meeting.state === 'AWAITING_SPEAKER_REVIEW' && (
        <SpeakerReview
          meetingId={meetingId}
          onSubmitted={(result) => {
            if (result.has_unconfirmed_speakers) {
              setNotice('本场含未确认说话人，纪要会带「含未确认说话人」标记')
            }
            toast('说话人确认已提交')
            refresh()
          }}
        />
      )}

      {RESULT_STATES.has(meeting.state) && (
        <ResultPanel meetingId={meetingId} state={meeting.state} onChanged={refresh} />
      )}

      {meeting.state === 'FAILED' && (
        <div className="notice notice-error">
          处理失败。请检查音频文件后新建会议重试。
        </div>
      )}
      {meeting.state === 'CANCELED' && (
        <div className="notice">这场会议已取消。</div>
      )}
    </div>
  )
}

function ResultPanel({
  meetingId,
  state,
  onChanged,
}: {
  meetingId: string
  state: string
  onChanged: () => void
}) {
  const [tab, setTab] = useState<'transcript' | 'minutes'>(
    state === 'PARTIAL_READY' ? 'transcript' : 'minutes',
  )
  // 转写默认展示清洗版；没有清洗版时 TranscriptView 自动落回原文，
  // 导出按钮跟随当前口径（后端对无清洗版的 cleaned 请求同样回退原文）。
  const [transcriptVariant, setTranscriptVariant] =
    useState<TranscriptVariant>('cleaned')
  // 是否有清洗版由 TranscriptView 加载后上报，决定工具栏是否出切换按钮。
  const [cleanedAvailable, setCleanedAvailable] = useState(false)
  const [reopening, setReopening] = useState(false)
  const [reopenError, setReopenError] = useState<string | null>(null)

  const handleReopen = async () => {
    setReopening(true)
    setReopenError(null)
    try {
      // 复用已有转写与切分，只重开确认停点；确认后仅重出纪要。
      await reopenReview(meetingId)
      onChanged()
    } catch (e: unknown) {
      setReopenError(formatApiError(e))
    } finally {
      setReopening(false)
    }
  }

  return (
    <section className="section">
      {state === 'PARTIAL_READY' && (
        <div className="notice notice-warn" style={{ marginBottom: 12 }}>
          音频已转写并完成说话人确认；生成纪要需要本机 Claude 或 Codex
          CLI，安装并登录后可在「纪要」页重试。
        </div>
      )}
      {reopenError !== null && (
        <div className="notice notice-error" style={{ marginBottom: 12 }}>
          {reopenError}
        </div>
      )}
      <div className="result-toolbar">
        <div className="tabs">
          <button
            type="button"
            className={`tab${tab === 'transcript' ? ' active' : ''}`}
            onClick={() => setTab('transcript')}
          >
            转写
          </button>
          <button
            type="button"
            className={`tab${tab === 'minutes' ? ' active' : ''}`}
            onClick={() => setTab('minutes')}
          >
            纪要
          </button>
        </div>
        <div className="export-links">
          {tab === 'transcript' && cleanedAvailable && (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() =>
                setTranscriptVariant(
                  transcriptVariant === 'cleaned' ? 'raw' : 'cleaned',
                )
              }
            >
              {transcriptVariant === 'cleaned' ? '查看原文' : '查看清洗版'}
            </button>
          )}
          <ResultActionsMenu
            meetingId={meetingId}
            state={state}
            transcriptVariant={transcriptVariant}
            reopening={reopening}
            onReopen={() => {
              void handleReopen()
            }}
          />
        </div>
      </div>
      {tab === 'transcript' ? (
        <TranscriptView
          meetingId={meetingId}
          variant={transcriptVariant}
          onCleanedAvailable={setCleanedAvailable}
        />
      ) : (
        <MinutesView
          meetingId={meetingId}
          canRetry={state === 'PARTIAL_READY'}
          onRetried={onChanged}
        />
      )}
    </section>
  )
}
