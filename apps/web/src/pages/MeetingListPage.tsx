import { useEffect, useState } from 'react'
import {
  deleteMeeting,
  formatApiError,
  listMeetings,
  listProjects,
  type Meeting,
  type Project,
} from '../api/client'
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

// 筛选值：all=全部 / none=无项目 / 其余是项目 id
const FILTER_KEY = 'meeting-workbench.project-filter'

function readStoredFilter(): string {
  try {
    return window.localStorage.getItem(FILTER_KEY) ?? 'all'
  } catch {
    return 'all'
  }
}

function storeFilter(value: string): void {
  try {
    window.localStorage.setItem(FILTER_KEY, value)
  } catch {
    // 隐私模式等场景写不进去，筛选照常工作，只是不记住
  }
}

export function MeetingListPage() {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [projectFilter, setProjectFilter] = useState<string>(readStoredFilter)
  const [error, setError] = useState<string | null>(null)
  // 删除走两段式确认：整场会议（音频、转写、纪要）一起消失，值得多点一下
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const awaitingCount =
    meetings?.filter((meeting) => meeting.state === 'AWAITING_SPEAKER_REVIEW')
      .length ?? 0
  // 纯本地筛选：列表一次拉全，切 pill 不再请求后端
  const visibleMeetings =
    meetings === null
      ? null
      : meetings.filter((meeting) => {
          if (projectFilter === 'all') return true
          if (projectFilter === 'none') return meeting.project_id === null
          return meeting.project_id === projectFilter
        })

  const pickFilter = (value: string) => {
    setProjectFilter(value)
    storeFilter(value)
  }

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

  // 项目只用来出筛选条：拉不到就当没有项目，不打断会议列表
  useEffect(() => {
    let stale = false
    listProjects()
      .then((items) => {
        if (!stale) {
          setProjects(items)
        }
      })
      .catch(() => {
        if (!stale) {
          setProjects([])
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

      {projects.length > 0 && (
        <div className="filter-bar">
          <div className="tabs" aria-label="按项目筛选">
            <button
              type="button"
              className={`tab${projectFilter === 'all' ? ' active' : ''}`}
              onClick={() => pickFilter('all')}
            >
              全部
            </button>
            <button
              type="button"
              className={`tab${projectFilter === 'none' ? ' active' : ''}`}
              onClick={() => pickFilter('none')}
            >
              无项目
            </button>
            {projects.map((project) => (
              <button
                key={project.id}
                type="button"
                className={`tab${projectFilter === project.id ? ' active' : ''}`}
                onClick={() => pickFilter(project.id)}
              >
                {project.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {error !== null && <div className="notice notice-error">{error}</div>}

      {meetings === null && error === null && <SkeletonListRows />}

      {visibleMeetings !== null && (
        <div className="list-card">
          {visibleMeetings.length === 0 ? (
            meetings !== null && meetings.length > 0 ? (
              <div className="empty">
                <div className="empty-title">这个项目下还没有会议</div>
                <div>换个项目，或者新建一场会议挂到它下面</div>
              </div>
            ) : (
              <div className="empty">
                <div className="empty-title">还没有会议</div>
                <div>新建一场会议并上传录音，开始第一次转写</div>
                <a className="btn" href="#/new">
                  <Icon name="plus" size={12} />
                  新建第一场会议
                </a>
              </div>
            )
          ) : (
            visibleMeetings.map((meeting) => (
              <div key={meeting.id} className="list-row">
                <a className="list-row-link" href={`#/meetings/${meeting.id}`}>
                  <span className="list-row-main">
                    <span className="list-row-headline">
                      <span className="list-row-title">{meeting.title}</span>
                      {meeting.project_name !== null && (
                        <span className="badge-project">{meeting.project_name}</span>
                      )}
                    </span>
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
