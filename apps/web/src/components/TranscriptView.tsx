import { useEffect, useState } from 'react'
import { formatApiError, getTranscriptMarkdown } from '../api/client'

interface TranscriptRow {
  time: string
  speaker: string
  text: string
}

// 后端导出为 PLAUD 风格段落块：标签行「{说话人} {mm:ss}-{mm:ss}」（超一小时为
// h:mm:ss）+ 合并文本行，块间空行；时间戳已格式化，前端不再换算。
const HEADER_PATTERN = /^(.+?)\s+(\d+:\d{2}(?::\d{2})?)-(\d+:\d{2}(?::\d{2})?)$/

function parseTranscript(markdown: string): TranscriptRow[] {
  const rows: TranscriptRow[] = []
  let current: TranscriptRow | null = null
  for (const raw of markdown.split('\n')) {
    const line = raw.trim()
    if (line === '' || line.startsWith('#')) {
      continue
    }
    const match = HEADER_PATTERN.exec(line)
    if (match !== null) {
      current = {
        time: `${match[2]} – ${match[3]}`,
        speaker: match[1],
        text: '',
      }
      rows.push(current)
    } else if (current !== null) {
      current.text = current.text === '' ? line : `${current.text} ${line}`
    }
  }
  return rows
}

export function TranscriptView({ meetingId }: { meetingId: string }) {
  const [markdown, setMarkdown] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let stale = false
    getTranscriptMarkdown(meetingId)
      .then((text) => {
        if (!stale) {
          setMarkdown(text)
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
  }, [meetingId])

  if (error !== null) {
    return <div className="notice notice-error">{error}</div>
  }
  if (markdown === null) {
    return <p className="section-desc">加载转写…</p>
  }

  const rows = parseTranscript(markdown)
  if (rows.length === 0) {
    return <pre className="speaker-text">{markdown}</pre>
  }
  return (
    <div className="card">
      {rows.map((row, index) => (
        <div key={index} className="transcript-row">
          <span className="transcript-time">{row.time}</span>
          <span className="transcript-speaker">{row.speaker}</span>
          <span className="transcript-text">{row.text}</span>
        </div>
      ))}
    </div>
  )
}
