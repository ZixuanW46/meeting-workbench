import { useState, type KeyboardEvent } from 'react'
import { createMeeting, formatApiError, localToday } from '../api/client'
import { Icon } from '../components/Icon'

export function NewMeetingPage() {
  const [title, setTitle] = useState('')
  const [titleError, setTitleError] = useState<string | null>(null)
  // 会议发生日：纪要标题与「明天」「下周二」换算都以它为锚点，默认今天
  const [meetingDate, setMeetingDate] = useState(localToday())
  const [hotwords, setHotwords] = useState<string[]>([])
  const [hotwordInput, setHotwordInput] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
    // 体验层拦截：标题必填；最终校验以后端 422 为准
    if (title.trim() === '') {
      setTitleError('请输入标题')
      return
    }
    setTitleError(null)
    setError(null)
    setSubmitting(true)
    try {
      const meeting = await createMeeting({
        title: title.trim(),
        hotwords,
        ...(meetingDate !== '' ? { meeting_date: meetingDate } : {}),
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
            className={`input${titleError !== null ? ' invalid' : ''}`}
            value={title}
            placeholder="例如：产品周会"
            onChange={(event) => {
              setTitle(event.target.value)
              if (titleError !== null && event.target.value.trim() !== '') {
                setTitleError(null)
              }
            }}
          />
          {titleError !== null && <span className="form-error">{titleError}</span>}
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
