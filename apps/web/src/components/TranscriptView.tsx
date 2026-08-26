import { useEffect, useState } from 'react'
import { formatApiError, getTranscriptMarkdown } from '../api/client'

interface TranscriptRow {
  time: string
  speaker: string
  text: string
}

// 后端导出行形如：[12.00-15.50] 张三：今天先对齐进度
const LINE_PATTERN = /^\[(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\]\s*(.+?)：(.*)$/

function formatSeconds(value: string): string {
  const total = Number(value)
  const minutes = Math.floor(total / 60)
  const seconds = Math.floor(total % 60)
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

function parseTranscript(markdown: string): TranscriptRow[] {
  const rows: TranscriptRow[] = []
  for (const line of markdown.split('\n')) {
    const match = LINE_PATTERN.exec(line.trim())
    if (match !== null) {
      rows.push({
        time: `${formatSeconds(match[1])} – ${formatSeconds(match[2])}`,
        speaker: match[3],
        text: match[4],
      })
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
