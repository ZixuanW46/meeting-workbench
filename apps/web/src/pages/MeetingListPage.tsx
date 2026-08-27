import { useEffect, useState } from 'react'
import { formatApiError, listMeetings, type Meeting } from '../api/client'
import { DoctorBanner } from '../components/DoctorBanner'
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
          <p className="page-subtitle">上传录音，确认说话人，得到转写与纪要</p>
        </div>
        <a className="btn btn-primary" href="#/new">
          新建会议
        </a>
      </div>

      <DoctorBanner />

      {error !== null && <div className="notice notice-error">{error}</div>}

      {meetings !== null && (
        <div className="list-card">
          {meetings.length === 0 ? (
            <div className="empty">
              <div className="empty-title">还没有会议</div>
              <div>新建一场会议并上传录音，开始第一次转写</div>
              <a className="btn" href="#/new">
                新建第一场会议
              </a>
            </div>
          ) : (
            meetings.map((meeting) => (
              <a
                key={meeting.id}
                className="list-row"
                href={`#/meetings/${meeting.id}`}
              >
                <span className="list-row-title">{meeting.title}</span>
                <StateBadge state={meeting.state} />
                <span className="list-row-meta">
                  {formatCreatedAt(meeting.created_at)}
                </span>
              </a>
            ))
          )}
        </div>
      )}
    </div>
  )
}
