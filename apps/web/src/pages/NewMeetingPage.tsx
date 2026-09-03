import { useEffect, useState, type KeyboardEvent } from 'react'
import {
  createMeeting,
  createProject,
  formatApiError,
  listProjects,
  localToday,
  type MeetingLanguage,
  type Project,
} from '../api/client'
import { Icon } from '../components/Icon'

// <select> 里的哨兵值：选中它就地展开新建项目输入
const NEW_PROJECT_OPTION = '__new__'

export function NewMeetingPage() {
  // 标题选填：留空先占位，上传后取录音文件名，纪要生成后自动命名
  const [title, setTitle] = useState('')
  // 会议发生日：纪要标题与「明天」「下周二」换算都以它为锚点，默认今天
  const [meetingDate, setMeetingDate] = useState(localToday())
  // 转写目标语言：默认中文，决定后续转写识别的语言
  const [language, setLanguage] = useState<MeetingLanguage>('zh')
  // 归属项目：空串 = 无项目；决定这场会议叠加哪份项目热词
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [creatingProject, setCreatingProject] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [savingProject, setSavingProject] = useState(false)
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

  const submitNewProject = () => {
    const name = newProjectName.trim()
    if (name === '' || savingProject) {
      return
    }
    setSavingProject(true)
    setError(null)
    createProject(name)
      .then((created) => {
        setProjects((current) => [...current, created])
        setProjectId(created.id)
        setNewProjectName('')
        setCreatingProject(false)
      })
      .catch((e: unknown) => {
        setError(formatApiError(e))
      })
      .finally(() => {
        setSavingProject(false)
      })
  }

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

  const handleSubmit = async () => {
    setError(null)
    setSubmitting(true)
    try {
      const trimmed = title.trim()
      const meeting = await createMeeting({
        ...(trimmed !== '' ? { title: trimmed } : {}),
        hotwords,
        ...(meetingDate !== '' ? { meeting_date: meetingDate } : {}),
        language,
        ...(projectId !== '' ? { project_id: projectId } : {}),
      })
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
        className="form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          void handleSubmit()
        }}
      >
        <div className="form-field">
          <label htmlFor="meeting-title">标题</label>
          <input
            id="meeting-title"
            className="input"
            value={title}
            placeholder="可留空，纪要生成后自动命名"
            onChange={(event) => setTitle(event.target.value)}
          />
          <span className="form-hint">
            留空则上传后先用录音文件名，纪要生成后按「日期：主题」自动命名；填了就以你的为准
          </span>
        </div>

        <div className="form-field">
          <label htmlFor="meeting-date">会议日期</label>
          <input
            id="meeting-date"
            type="date"
            className="input input-date"
            value={meetingDate}
            onChange={(event) => setMeetingDate(event.target.value)}
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
          <select
            id="meeting-project"
            className="select"
            value={creatingProject ? NEW_PROJECT_OPTION : projectId}
            onChange={(event) => {
              const value = event.target.value
              if (value === NEW_PROJECT_OPTION) {
                setCreatingProject(true)
                return
              }
              setCreatingProject(false)
              setProjectId(value)
            }}
          >
            <option value="">无项目</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
            <option value={NEW_PROJECT_OPTION}>新建项目…</option>
          </select>
          {creatingProject && (
            <div className="inline-create">
              <input
                className="input"
                aria-label="新项目名字"
                placeholder="项目名字，回车创建"
                value={newProjectName}
                disabled={savingProject}
                autoFocus
                onChange={(event) => setNewProjectName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    submitNewProject()
                  }
                  if (event.key === 'Escape') {
                    setCreatingProject(false)
                    setNewProjectName('')
                  }
                }}
              />
              <button
                type="button"
                className="btn"
                disabled={savingProject || newProjectName.trim() === ''}
                onClick={submitNewProject}
              >
                创建
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={savingProject}
                onClick={() => {
                  setCreatingProject(false)
                  setNewProjectName('')
                }}
              >
                取消
              </button>
            </div>
          )}
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

        <div>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            创建会议
          </button>
        </div>
      </form>
    </div>
  )
}
