import { useEffect, useState } from 'react'
import { deleteMeeting, formatApiError, listMeetings, type Meeting } from '../api/client'
import { DoctorBanner } from '../components/DoctorBanner'
import { SkeletonListRows } from '../components/Skeleton'
import { toast } from '../components/Toast'
import { Icon } from '../components/Icon'
import { StateBadge } from '../components/StateBadge'

function formatCreatedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function MeetingListPage() {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // 删除走两段式确认：整场会议（音频、转写、纪要）一起消失，值得多点一下
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const awaitingCount =
    meetings?.filter((meeting) => meeting.state === 'AWAITING_SPEAKER_REVIEW')
      .length ?? 0

  const onDelete = (meetingId: string, title: string) => {
    setDeletingId(meetingId)
    setError(null)
    deleteMeeting(meetingId)
      .then(() => {
        setMeetings((current) =>
          current === null ? current : current.filter((m) => m.id !== meetingId),
        )
        toast(`已删除「${title}」`)
      })
      .catch((e: unknown) => {
        setError(formatApiError(e))
        toast(formatApiError(e), 'error')
      })
      .finally(() => {
        setDeletingId(null)
        setConfirmingId(null)
      })
  }

  useEffect(() => {
    let stale = false
    listMeetings()
      .then((items) => {
        if (!stale) {
          setMeetings(items)
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

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">会议</h1>
          <p className="page-subtitle">
            {meetings !== null && meetings.length > 0
              ? `${meetings.length} 场会议${
                  awaitingCount > 0 ? ` · ${awaitingCount} 场等你确认说话人` : ''
                }`
              : '上传录音，确认说话人，得到转写与纪要'}
          </p>
        </div>
        <a className="btn btn-primary" href="#/new">
          <Icon name="plus" size={12} />
          新建会议
        </a>
      </div>

      <DoctorBanner />

      {error !== null && <div className="notice notice-error">{error}</div>}

      {meetings === null && error === null && <SkeletonListRows />}

      {meetings !== null && (
        <div className="list-card">
          {meetings.length === 0 ? (
            <div className="empty">
              <div className="empty-title">还没有会议</div>
              <div>新建一场会议并上传录音，开始第一次转写</div>
              <a className="btn" href="#/new">
                <Icon name="plus" size={12} />
                新建第一场会议
              </a>
            </div>
          ) : (
            meetings.map((meeting) => (
              <div key={meeting.id} className="list-row">
                <a className="list-row-link" href={`#/meetings/${meeting.id}`}>
                  <span className="list-row-main">
                    <span className="list-row-title">{meeting.title}</span>
                    <span className="list-row-meta">
                      {meeting.speakers.length + meeting.unknown_speaker_count > 0
                        ? `参会 ${meeting.speakers.length + meeting.unknown_speaker_count} 人 · `
                        : ''}
                      {formatCreatedAt(meeting.created_at)}
                    </span>
                  </span>
                  {meeting.language === 'en' && <span className="badge-lang">EN</span>}
                  <StateBadge state={meeting.state} />
                  <Icon name="chevron-right" size={12} className="list-row-chevron" />
                </a>
                {confirmingId === meeting.id ? (
                  <span className="row-actions">
                    <button
                      type="button"
                      className="btn btn-danger"
                      disabled={deletingId === meeting.id}
                      onClick={() => onDelete(meeting.id, meeting.title)}
                    >
                      确认删除
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      disabled={deletingId === meeting.id}
                      onClick={() => setConfirmingId(null)}
                    >
                      取消
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn btn-ghost row-delete"
                    aria-label={`删除会议 ${meeting.title}`}
                    onClick={() => setConfirmingId(meeting.id)}
                  >
                    <Icon name="trash" size={12} />
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
