import { useCallback, useEffect, useRef, useState } from 'react'
import {
  exportUrls,
  formatApiError,
  getMeeting,
  reopenReview,
  type Meeting,
} from '../api/client'
import { DoctorBanner } from '../components/DoctorBanner'
import { Icon } from '../components/Icon'
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
  const meetingStateRef = useRef<string | null>(null)
  meetingStateRef.current = meeting?.state ?? null

  const refresh = useCallback(() => {
    getMeeting(meetingId)
      .then((data) => {
        setMeeting(data)
        setError(null)
      })
      .catch((e: unknown) => setError(formatApiError(e)))
  }, [meetingId])

  useEffect(() => {
    refresh()
  }, [refresh])

  if (meeting === null) {
    return (
      <div className="page">
        <a className="back-link" href="#/">
          <Icon name="chevron-left" size={12} />
          返回会议列表
        </a>
        {error !== null ? (
          <div className="notice notice-error">{error}</div>
        ) : (
          <p className="section-desc">加载会议…</p>
        )}
      </div>
    )
  }

  return (
    <div className="page">
      <a className="back-link" href="#/">
        <Icon name="chevron-left" size={12} />
        返回会议列表
      </a>
      <div className="page-header">
        <div>
          <h1 className="page-title">{meeting.title}</h1>
          <div className="meta-row" style={{ marginTop: 4 }}>
            <StateBadge state={meeting.state} />
            <span className="divider-dot" />
            <span>
              预计人数：
              {meeting.expected_speakers === null
                ? '不确定'
                : `${meeting.expected_speakers} 人`}
            </span>
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
          expectedSpeakers={meeting.expected_speakers}
          onSubmitted={(result) => {
            if (result.has_unconfirmed_speakers) {
              setNotice('本场含未确认说话人，纪要会带「含未确认说话人」标记')
            }
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
          <button
            type="button"
            className="btn"
            disabled={reopening}
            onClick={() => {
              void handleReopen()
            }}
          >
            重新确认说话人
          </button>
          <a className="btn" href={exportUrls.transcriptMd(meetingId)} download>
            <Icon name="download" size={12} />
            导出转写 MD
          </a>
          {state === 'READY' && (
            <>
              <a className="btn" href={exportUrls.minutesMd(meetingId)} download>
                <Icon name="download" size={12} />
                导出纪要 MD
              </a>
              <a className="btn" href={exportUrls.minutesDocx(meetingId)} download>
                <Icon name="download" size={12} />
                导出纪要 DOCX
              </a>
            </>
          )}
        </div>
      </div>
      {tab === 'transcript' ? (
        <TranscriptView meetingId={meetingId} />
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
