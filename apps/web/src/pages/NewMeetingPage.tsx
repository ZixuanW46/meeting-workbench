import { useEffect, useState, type KeyboardEvent } from 'react'
import {
  createMeeting,
  formatApiError,
  importPlaudRecording,
  listProjects,
  localToday,
  type MeetingLanguage,
  type PlaudRecording,
  type Project,
} from '../api/client'
import { Icon } from '../components/Icon'
import { InlineProjectCreate } from '../components/InlineProjectCreate'
import { PlaudRecordingPicker, recordingLocalDate } from '../components/PlaudRecordingPicker'
import { toast } from '../components/Toast'

/** 录音来源：upload=先建会议稍后上传文件 / plaud=从 Plaud 云端导入 */
type MeetingSource = 'upload' | 'plaud'

/** #/new?source=plaud 打开即停在 Plaud 那一侧；其余情况都是默认的上传路径 */
function initialSource(): MeetingSource {
  const hash = window.location.hash
  const queryAt = hash.indexOf('?')
  if (queryAt === -1) {
    return 'upload'
  }
  return new URLSearchParams(hash.slice(queryAt + 1)).get('source') === 'plaud'
    ? 'plaud'
    : 'upload'
}

export function NewMeetingPage() {
  // 录音来源决定提交走哪条接口：上传路径只建会议，Plaud 路径连音频一起拿回来
  const [source, setSource] = useState<MeetingSource>(initialSource)
  const [recording, setRecording] = useState<PlaudRecording | null>(null)
  // 标题选填：留空先占位，上传后取录音文件名，纪要生成后自动命名
  const [title, setTitle] = useState('')
  // 会议发生日：纪要标题与「明天」「下周二」换算都以它为锚点，默认今天
  const [meetingDate, setMeetingDate] = useState(localToday())
  // 用户自己动过日期后，选录音就不再覆盖它
  const [meetingDateTouched, setMeetingDateTouched] = useState(false)
  // 转写目标语言：默认中文，决定后续转写识别的语言
  const [language, setLanguage] = useState<MeetingLanguage>('zh')
  // 归属项目：空串 = 无项目；决定这场会议叠加哪份项目热词
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [hotwords, setHotwords] = useState<string[]>([])
  const [hotwordInput, setHotwordInput] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

  const addHotword = () => {
    const word = hotwordInput.trim()
    if (word !== '' && !hotwords.includes(word)) {
      setHotwords([...hotwords, word])
    }
    setHotwordInput('')
  }

  const handleHotwordKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      addHotword()
    } else if (event.key === 'Backspace' && hotwordInput === '' && hotwords.length > 0) {
      setHotwords(hotwords.slice(0, -1))
    }
  }

  const pickRecording = (picked: PlaudRecording) => {
    setRecording(picked)
    const localDate = recordingLocalDate(picked.started_at)
    if (!meetingDateTouched && localDate !== '') {
      setMeetingDate(localDate)
    }
  }

  const importing = source === 'plaud'
  const handleSubmit = async () => {
    setError(null)
    setSubmitting(true)
    try {
      const trimmed = title.trim()
      const input = {
        ...(trimmed !== '' ? { title: trimmed } : {}),
        hotwords,
        ...(meetingDate !== '' ? { meeting_date: meetingDate } : {}),
        language,
        ...(projectId !== '' ? { project_id: projectId } : {}),
      }
      const meeting =
        importing && recording !== null
          ? await importPlaudRecording({ ...input, plaud_file_id: recording.file_id })
          : await createMeeting(input)
      if (importing && recording !== null) {
        toast(`已从 Plaud 导入「${recording.name}」`)
      }
      window.location.hash = `#/meetings/${meeting.id}`
    } catch (e: unknown) {
      setError(formatApiError(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page">
      <a className="back-link" href="#/">
        <Icon name="chevron-left" size={12} />
        返回会议列表
      </a>
      <div className="page-header">
        <div>
          <h1 className="page-title">新建会议</h1>
          <p className="page-subtitle">创建后上传录音开始处理；全程在本机完成</p>
        </div>
      </div>

      <form
        className={`form${importing ? ' form-wide' : ''}`}
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          void handleSubmit()
        }}
      >
        <div className="form-field">
          <label id="meeting-source-label">录音来源</label>
          <div className="tabs" aria-labelledby="meeting-source-label">
            <button
              type="button"
              className={`tab${!importing ? ' active' : ''}`}
              onClick={() => setSource('upload')}
            >
              稍后上传文件
            </button>
            <button
              type="button"
              className={`tab${importing ? ' active' : ''}`}
              onClick={() => setSource('plaud')}
            >
              从 Plaud 导入
            </button>
          </div>
          <span className="form-hint">
            {importing
              ? '从 Plaud 云端挑一条录音，创建后直接下载并开始处理'
              : '先建好会议，稍后在工作台上传录音文件'}
          </span>
        </div>

        {importing && (
          <div className="form-field">
            <label id="plaud-recording-label">选择录音</label>
            <PlaudRecordingPicker value={recording} onChange={pickRecording} />
          </div>
        )}

        <div className="form-field">
          <label htmlFor="meeting-title">标题</label>
          <input
            id="meeting-title"
            className="input"
            value={title}
            placeholder={
              importing && recording !== null
                ? recording.name
                : '可留空，纪要生成后自动命名'
            }
            onChange={(event) => setTitle(event.target.value)}
          />
          <span className="form-hint">
            {importing
              ? '留空则先用 Plaud 上的录音名；那名字要还是设备默认的时间串，纪要生成后会自动改名'
              : '留空则上传后先用录音文件名，纪要生成后按「日期：主题」自动命名；填了就以你的为准'}
          </span>
        </div>

        <div className="form-field">
          <label htmlFor="meeting-date">会议日期</label>
          <input
            id="meeting-date"
            type="date"
            className="input input-date"
            value={meetingDate}
            onChange={(event) => {
              setMeetingDate(event.target.value)
              setMeetingDateTouched(true)
            }}
          />
          <span className="form-hint">
            录音是哪天开的会；纪要标题与「明天」「下周二」的换算都以此为准
          </span>
        </div>

        <div className="form-field">
          <label id="meeting-language-label">语言</label>
          <div className="tabs" aria-labelledby="meeting-language-label">
            <button
              type="button"
              className={`tab${language === 'zh' ? ' active' : ''}`}
              onClick={() => setLanguage('zh')}
            >
              中文
            </button>
            <button
              type="button"
              className={`tab${language === 'en' ? ' active' : ''}`}
              onClick={() => setLanguage('en')}
            >
              English
            </button>
          </div>
          <span className="form-hint">决定转写识别的语言；创建后仍可在工作台修改，下次转写才生效</span>
        </div>

        <div className="form-field">
          <label htmlFor="meeting-project">项目</label>
          <div className="field-row">
            <select
              id="meeting-project"
              className="select"
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
            >
              <option value="">无项目</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
            <InlineProjectCreate
              onCreated={(created) => {
                setProjects((current) => [...current, created])
                setProjectId(created.id)
              }}
            />
          </div>
          <span className="form-hint">
            项目决定这场会议叠加哪份项目热词；不选就是无项目，只用通用词库
          </span>
        </div>

        <div className="form-field">
          <label htmlFor="meeting-hotwords">本场热词</label>
          <div className="tag-input">
            {hotwords.map((word) => (
              <span key={word} className="tag">
                {word}
                <button
                  type="button"
                  aria-label={`移除热词 ${word}`}
                  onClick={() => setHotwords(hotwords.filter((w) => w !== word))}
                >
                  <Icon name="close" size={10} />
                </button>
              </span>
            ))}
            <input
              id="meeting-hotwords"
              value={hotwordInput}
              placeholder="输入后回车添加"
              onChange={(event) => setHotwordInput(event.target.value)}
              onKeyDown={handleHotwordKeyDown}
              onBlur={addHotword}
            />
          </div>
          <span className="form-hint">帮助转写认出专有名词，如产品名、人名</span>
        </div>

        {error !== null && <div className="notice notice-error">{error}</div>}

        <div className="form-actions">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={submitting || (importing && recording === null)}
          >
            {importing ? '导入并开始处理' : '创建会议'}
          </button>
          {importing && submitting && (
            <span className="form-hint">
              正在从 Plaud 下载录音，大文件可能需要一两分钟…
            </span>
          )}
        </div>
      </form>
    </div>
  )
}
