import { useCallback, useEffect, useRef, useState } from 'react'
import {
  exportUrls,
  formatApiError,
  getMeeting,
  uploadAudio,
  type Meeting,
} from '../api/client'
import { MinutesView } from '../components/MinutesView'
import { Progress } from '../components/Progress'
import { SpeakerReview } from '../components/SpeakerReview'
import { StateBadge } from '../components/StateBadge'
import { TranscriptView } from '../components/TranscriptView'

const PROGRESS_STATES = new Set([
  'UPLOADING',
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
          ← 返回会议列表
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
        ← 返回会议列表
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

      {error !== null && <div className="notice notice-error">{error}</div>}
      {notice !== null && (
        <div className="notice notice-warn" style={{ marginBottom: 12 }}>
          {notice}
        </div>
      )}

      {meeting.state === 'DRAFT' && (
        <UploadPanel meetingId={meetingId} onUploaded={refresh} />
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

function UploadPanel({
  meetingId,
  onUploaded,
}: {
  meetingId: string
  onUploaded: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleUpload = async () => {
    if (file === null) {
      return
    }
    setUploading(true)
    setError(null)
    try {
      await uploadAudio(meetingId, file)
      onUploaded()
    } catch (e: unknown) {
      setError(formatApiError(e))
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="upload-panel">
      <div>
        <div className="section-title">上传会议录音</div>
        <div className="section-desc">音频只在本机处理，不会上传到云端</div>
      </div>
      <input
        type="file"
        accept="audio/*"
        aria-label="选择音频文件"
        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
      />
      {file !== null && <span className="upload-filename">{file.name}</span>}
      {error !== null && <div className="notice notice-error">{error}</div>}
      <button
        type="button"
        className="btn btn-primary"
        disabled={file === null || uploading}
        onClick={() => {
          void handleUpload()
        }}
      >
        {uploading ? '上传中…' : '上传音频'}
      </button>
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

  return (
    <section className="section">
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
          <a className="btn" href={exportUrls.transcriptMd(meetingId)} download>
            导出转写 MD
          </a>
          {state === 'READY' && (
            <>
              <a className="btn" href={exportUrls.minutesMd(meetingId)} download>
                导出纪要 MD
              </a>
              <a className="btn" href={exportUrls.minutesDocx(meetingId)} download>
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
