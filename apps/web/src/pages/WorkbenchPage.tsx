import { useCallback, useEffect, useRef, useState } from 'react'
import {
  cancelMeeting,
  formatApiError,
  getMeeting,
  listProjects,
  reopenReview,
  retranscribeMeeting,
  updateMeeting,
  updateMeetingTitle,
  type Meeting,
  type MeetingLanguage,
  type Project,
  type TranscriptVariant,
} from '../api/client'
import { ResultActionsMenu } from '../components/ResultActionsMenu'
import { DoctorBanner } from '../components/DoctorBanner'
import { Icon } from '../components/Icon'
import { InlineProjectCreate } from '../components/InlineProjectCreate'
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
  // 会议日期就地编辑：与标题同一套交互
  const [editingDate, setEditingDate] = useState(false)
  const [dateDraft, setDateDraft] = useState('')
  const [savingDate, setSavingDate] = useState(false)
  // 语言就地编辑：同一套交互，草稿用分段控件而非文本框；改动只影响下一次转写
  const [editingLanguage, setEditingLanguage] = useState(false)
  const [languageDraft, setLanguageDraft] = useState<MeetingLanguage>('zh')
  const [savingLanguage, setSavingLanguage] = useState(false)
  // 项目就地编辑：同一套交互，草稿用 <select>；改挂不改状态，热词下次转写才生效
  const [projects, setProjects] = useState<Project[]>([])
  const [editingProject, setEditingProject] = useState(false)
  const [projectDraft, setProjectDraft] = useState('')
  const [savingProject, setSavingProject] = useState(false)
  const [canceling, setCanceling] = useState(false)
  // 停止/取消是不可逆动作：先出确认条再发请求，和列表页删除、词库改范围同一套两段式
  const [confirmingCancel, setConfirmingCancel] = useState(false)
  const meetingStateRef = useRef<string | null>(null)
  meetingStateRef.current = meeting?.state ?? null
  // 不选项目的会议落在默认项目下：元信息行直接写项目名，不再有「无项目」这一态
  const defaultProject = projects.find((project) => project.is_default) ?? null
  const projectLabel = meeting?.project_name ?? defaultProject?.name ?? 'General'

  const refresh = useCallback(() => {
    getMeeting(meetingId)
      .then((data) => {
        // 纪要在后台生成完的那一次刷新，给个明确的完成反馈
        const previous = meetingStateRef.current
        if (previous !== null && previous !== 'READY' && data.state === 'READY') {
          toast('纪要已生成')
        }
        // 「含未确认说话人」提示只在纪要生成期间有意义：纪要本身会带标记
        if (data.state === 'READY' || data.state === 'PARTIAL_READY') {
          setNotice(null)
        }
        setMeeting(data)
        setError(null)
      })
      .catch((e: unknown) => setError(formatApiError(e)))
  }, [meetingId])

  useEffect(() => {
    refresh()
  }, [refresh])

  // 状态一变（自己取消成功、或后台自己跑完了），残留的确认条就该收掉
  useEffect(() => {
    setConfirmingCancel(false)
  }, [meeting?.state])

  // 项目只用于改挂的下拉选项：拉不到就当没有项目，不打断工作台
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

  const saveDate = async () => {
    if (meeting === null || dateDraft === '') return
    if (dateDraft === meeting.meeting_date && meeting.meeting_date_source === 'user') {
      setEditingDate(false)
      return
    }
    setSavingDate(true)
    try {
      const updated = await updateMeeting(meetingId, { meeting_date: dateDraft })
      setMeeting(updated)
      setEditingDate(false)
      setError(null)
      toast('会议日期已更新')
    } catch (e: unknown) {
      setError(formatApiError(e))
    } finally {
      setSavingDate(false)
    }
  }

  const saveLanguage = async () => {
    if (meeting === null) return
    if (languageDraft === meeting.language) {
      setEditingLanguage(false)
      return
    }
    setSavingLanguage(true)
    try {
      const updated = await updateMeeting(meetingId, { language: languageDraft })
      setMeeting(updated)
      setEditingLanguage(false)
      setError(null)
      toast('语言已更新，下次转写生效')
    } catch (e: unknown) {
      setError(formatApiError(e))
    } finally {
      setSavingLanguage(false)
    }
  }

  const saveProject = async () => {
    if (meeting === null) return
    // 草稿总停在某个项目上（不选项目的会议挂在默认项目下），空串只在项目还没回来时出现
    const next = projectDraft === '' ? null : projectDraft
    if (next === meeting.project_id) {
      setEditingProject(false)
      return
    }
    setSavingProject(true)
    try {
      const updated = await updateMeeting(meetingId, { project_id: next })
      setMeeting(updated)
      setEditingProject(false)
      setError(null)
      toast('项目已更新，热词在下次转写生效')
    } catch (e: unknown) {
      setError(formatApiError(e))
    } finally {
      setSavingProject(false)
    }
  }

  const cancel = async () => {
    setCanceling(true)
    try {
      const updated = await cancelMeeting(meetingId)
      setMeeting(updated)
      setError(null)
      toast(updated.state === 'PARTIAL_READY' ? '已停止生成纪要' : '已取消处理')
    } catch (e: unknown) {
      setError(formatApiError(e))
    } finally {
      setCanceling(false)
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

  // 生成纪要中停止只丢纪要（落 PARTIAL_READY），其余处理中状态停下来是整场取消
  const stoppingMinutes = meeting.state === 'GENERATING_MINUTES'

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
            <span className="divider-dot" />
            {editingDate ? (
              <span className="meta-edit-row">
                <input
                  type="date"
                  className="input input-date"
                  aria-label="会议日期"
                  value={dateDraft}
                  disabled={savingDate}
                  autoFocus
                  onChange={(event) => setDateDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault()
                      void saveDate()
                    }
                    if (event.key === 'Escape') {
                      setEditingDate(false)
                    }
                  }}
                />
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={savingDate || dateDraft === ''}
                  onClick={() => {
                    void saveDate()
                  }}
                >
                  保存
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={savingDate}
                  onClick={() => setEditingDate(false)}
                >
                  取消
                </button>
              </span>
            ) : (
              <span className="meta-date">
                <span>{`会议日期 ${meeting.meeting_date}`}</span>
                {meeting.meeting_date_source !== 'user' && (
                  <span className="meta-hint">
                    {meeting.meeting_date_source === 'filename'
                      ? '按文件名推断'
                      : '按创建日'}
                  </span>
                )}
                <button
                  type="button"
                  className="btn btn-ghost meta-edit-btn"
                  aria-label="修改会议日期"
                  onClick={() => {
                    setDateDraft(meeting.meeting_date)
                    setEditingDate(true)
                  }}
                >
                  <Icon name="edit" size={11} />
                </button>
              </span>
            )}
            <span className="divider-dot" />
            {editingLanguage ? (
              <span className="meta-edit-row">
                <div className="tabs" aria-label="会议语言">
                  <button
                    type="button"
                    className={`tab${languageDraft === 'zh' ? ' active' : ''}`}
                    disabled={savingLanguage}
                    onClick={() => setLanguageDraft('zh')}
                  >
                    中文
                  </button>
                  <button
                    type="button"
                    className={`tab${languageDraft === 'en' ? ' active' : ''}`}
                    disabled={savingLanguage}
                    onClick={() => setLanguageDraft('en')}
                  >
                    English
                  </button>
                </div>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={savingLanguage}
                  onClick={() => {
                    void saveLanguage()
                  }}
                >
                  保存
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={savingLanguage}
                  onClick={() => setEditingLanguage(false)}
                >
                  取消
                </button>
              </span>
            ) : (
              <span className="meta-date">
                <span>{`语言 ${meeting.language === 'en' ? 'English' : '中文'}`}</span>
                <button
                  type="button"
                  className="btn btn-ghost meta-edit-btn"
                  aria-label="修改会议语言"
                  onClick={() => {
                    setLanguageDraft(meeting.language)
                    setEditingLanguage(true)
                  }}
                >
                  <Icon name="edit" size={11} />
                </button>
              </span>
            )}
            <span className="divider-dot" />
            {editingProject ? (
              <span className="meta-edit-row">
                <select
                  className="select meta-select"
                  aria-label="会议项目"
                  value={projectDraft}
                  disabled={savingProject}
                  autoFocus
                  onChange={(event) => setProjectDraft(event.target.value)}
                >
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
                {/* 新建后只落到草稿：仍要点「保存」才 PATCH，语义和选已有项目一致 */}
                <InlineProjectCreate
                  onCreated={(created) => {
                    setProjects((current) => [...current, created])
                    setProjectDraft(created.id)
                  }}
                />
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={savingProject}
                  onClick={() => {
                    void saveProject()
                  }}
                >
                  保存
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={savingProject}
                  onClick={() => setEditingProject(false)}
                >
                  取消
                </button>
              </span>
            ) : (
              <span className="meta-date">
                <span>{`项目 ${projectLabel}`}</span>
                <button
                  type="button"
                  className="btn btn-ghost meta-edit-btn"
                  aria-label="修改会议项目"
                  onClick={() => {
                    setProjectDraft(meeting.project_id ?? defaultProject?.id ?? '')
                    setEditingProject(true)
                  }}
                >
                  <Icon name="edit" size={11} />
                </button>
              </span>
            )}
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
        <div className="progress-stage">
          <Progress
            meetingId={meetingId}
            onSnapshot={(snapshot) => {
              if (snapshot.state !== meetingStateRef.current) {
                refresh()
              }
            }}
          />
          {/* 决定应用在请求内瞬间完成，不给取消；其余处理中状态都可停 */}
          {meeting.state !== 'APPLYING_DECISIONS' &&
            (confirmingCancel ? (
              <div className="progress-confirm">
                <div className="progress-confirm-text">
                  {stoppingMinutes
                    ? '停止后转写与已确认的说话人都保留，只是这次不出纪要，可稍后在「纪要」页重新生成。'
                    : '取消后这场会议会标记为已取消，音频仍在本机，可在页面重新处理。'}
                </div>
                <div className="progress-confirm-actions">
                  <button
                    type="button"
                    className="btn btn-danger"
                    disabled={canceling}
                    onClick={() => {
                      void cancel()
                    }}
                  >
                    {stoppingMinutes ? '确认停止' : '确认取消'}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={canceling}
                    onClick={() => setConfirmingCancel(false)}
                  >
                    {stoppingMinutes ? '继续生成' : '继续处理'}
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                className="btn btn-ghost progress-cancel"
                disabled={canceling}
                onClick={() => setConfirmingCancel(true)}
              >
                {stoppingMinutes ? '停止生成纪要' : '取消处理'}
              </button>
            ))}
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
        <ResultPanel
          meetingId={meetingId}
          state={meeting.state}
          processingError={meeting.processing_error}
          onChanged={refresh}
        />
      )}

      {(meeting.state === 'FAILED' || meeting.state === 'CANCELED') && (
        <RecoveryPanel meeting={meeting} onChanged={refresh} />
      )}
    </div>
  )
}

/** FAILED / CANCELED：音频还在盘上，给出原因并允许放回队列重跑。 */
function RecoveryPanel({
  meeting,
  onChanged,
}: {
  meeting: Meeting
  onChanged: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const failed = meeting.state === 'FAILED'

  const retry = async () => {
    setBusy(true)
    setError(null)
    try {
      await retranscribeMeeting(meeting.id)
      toast('已重新放回队列')
      onChanged()
    } catch (e: unknown) {
      setError(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`notice ${failed ? 'notice-error' : ''} recovery-panel`}>
      <div className="recovery-body">
        <div>{failed ? '处理失败。' : '这场会议已取消。'}</div>
        {failed && meeting.processing_error !== null && (
          <div className="recovery-reason">{meeting.processing_error}</div>
        )}
        <div className="form-hint">
          音频仍保存在本机；重新处理会从校验与转写重新开始。
        </div>
        {error !== null && <div className="form-error">{error}</div>}
      </div>
      <button
        type="button"
        className="btn"
        disabled={busy}
        onClick={() => {
          void retry()
        }}
      >
        <Icon name="refresh" size={12} />
        重新处理
      </button>
    </div>
  )
}

function ResultPanel({
  meetingId,
  state,
  processingError,
  onChanged,
}: {
  meetingId: string
  state: string
  processingError: string | null
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
  // 重新转写会丢掉已确认的说话人与纪要：菜单点了先出确认条，再发请求。
  const [confirmingRetranscribe, setConfirmingRetranscribe] = useState(false)

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

  const handleRetranscribe = async () => {
    setReopening(true)
    setReopenError(null)
    try {
      await retranscribeMeeting(meetingId)
      setConfirmingRetranscribe(false)
      toast('已重新放回队列')
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
          <div>
            <div>
              音频已转写并完成说话人确认；生成纪要需要本机 Claude 或 Codex
              CLI，安装并登录后可在「纪要」页重试。
            </div>
            {processingError !== null && (
              <div className="recovery-reason">{processingError}</div>
            )}
          </div>
        </div>
      )}
      {confirmingRetranscribe && (
        <div className="notice notice-warn" style={{ marginBottom: 12 }}>
          <span style={{ flex: 1 }}>
            重新转写会丢弃已确认的说话人与现有纪要，音频不动。确定继续？
          </span>
          <span className="row-actions">
            <button
              type="button"
              className="btn btn-danger"
              disabled={reopening}
              onClick={() => {
                void handleRetranscribe()
              }}
            >
              确认重新转写
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={reopening}
              onClick={() => setConfirmingRetranscribe(false)}
            >
              取消
            </button>
          </span>
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
            onRetranscribe={() => setConfirmingRetranscribe(true)}
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
