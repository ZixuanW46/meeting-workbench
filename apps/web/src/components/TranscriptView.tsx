import { useEffect, useState } from 'react'
import {
  formatApiError,
  getTranscript,
  type TranscriptResult,
  type TranscriptVariant,
} from '../api/client'

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

export function TranscriptView({
  meetingId,
  variant,
  onCleanedAvailable,
}: {
  meetingId: string
  variant: TranscriptVariant
  /** 加载后告知父组件是否有清洗版，工具栏据此决定是否出切换按钮 */
  onCleanedAvailable?: (available: boolean) => void
}) {
  const [transcript, setTranscript] = useState<TranscriptResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let stale = false
    getTranscript(meetingId)
      .then((data) => {
        if (!stale) {
          setTranscript(data)
          onCleanedAvailable?.(data.cleaned_markdown !== null)
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
    // onCleanedAvailable 是父组件的稳定 setState，不进依赖免得重复拉取。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingId])

  if (error !== null) {
    return <div className="notice notice-error">{error}</div>
  }
  if (transcript === null) {
    return <p className="section-desc">加载转写…</p>
  }

  // 没有可用清洗版时只有原文一个口径；切换按钮在工作台工具栏。
  const showCleaned =
    transcript.cleaned_markdown !== null && variant === 'cleaned'
  const markdown = showCleaned
    ? (transcript.cleaned_markdown as string)
    : transcript.raw_markdown

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
