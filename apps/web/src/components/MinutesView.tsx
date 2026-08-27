import { Fragment, useEffect, useState } from 'react'
import {
  ApiError,
  formatApiError,
  getMinutes,
  retryMinutes,
  type MinutesResult,
} from '../api/client'
import { Icon } from './Icon'

interface MinutesViewProps {
  meetingId: string
  /** PARTIAL_READY 时为 true：显示失败说明和重试按钮 */
  canRetry: boolean
  onRetried: () => void
}

// 极简 markdown 渲染：标题 / 列表 / 段落，纪要内容不需要更多
function renderMarkdown(markdown: string) {
  const blocks: Array<{ type: 'heading' | 'paragraph'; text: string } | { type: 'list'; items: string[] }> = []
  for (const rawLine of markdown.split('\n')) {
    const line = rawLine.trim()
    if (line === '') {
      continue
    }
    if (line.startsWith('#')) {
      blocks.push({ type: 'heading', text: line.replace(/^#+\s*/, '') })
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      const last = blocks[blocks.length - 1]
      const item = line.slice(2)
      if (last !== undefined && last.type === 'list') {
        last.items.push(item)
      } else {
        blocks.push({ type: 'list', items: [item] })
      }
    } else {
      blocks.push({ type: 'paragraph', text: line })
    }
  }
  return blocks.map((block, index) => {
    if (block.type === 'heading') {
      return <h3 key={index}>{block.text}</h3>
    }
    if (block.type === 'list') {
      return (
        <ul key={index}>
          {block.items.map((item, itemIndex) => (
            <li key={itemIndex}>{item}</li>
          ))}
        </ul>
      )
    }
    return <p key={index}>{block.text}</p>
  })
}

export function MinutesView({ meetingId, canRetry, onRetried }: MinutesViewProps) {
  const [minutes, setMinutes] = useState<MinutesResult | null>(null)
  const [notReady, setNotReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)

  useEffect(() => {
    let stale = false
    getMinutes(meetingId)
      .then((result) => {
        if (!stale) {
          setMinutes(result)
        }
      })
      .catch((e: unknown) => {
        if (stale) {
          return
        }
        if (e instanceof ApiError && e.status === 409) {
          setNotReady(true)
        } else {
          setError(formatApiError(e))
        }
      })
    return () => {
      stale = true
    }
  }, [meetingId])

  const handleRetry = async () => {
    setRetrying(true)
    setError(null)
    try {
      await retryMinutes(meetingId)
      onRetried()
    } catch (e: unknown) {
      setError(formatApiError(e))
    } finally {
      setRetrying(false)
    }
  }

  return (
    <Fragment>
      {canRetry && (
        <div className="notice notice-warn" style={{ marginBottom: 12 }}>
          <span>纪要生成失败（转写不受影响，仍可导出）。</span>
          <button
            type="button"
            className="btn"
            disabled={retrying}
            onClick={() => {
              void handleRetry()
            }}
          >
            <Icon name="refresh" size={12} />
            重试生成纪要
          </button>
        </div>
      )}
      {error !== null && <div className="notice notice-error">{error}</div>}
      {minutes !== null && (
        <Fragment>
          <div className="notice notice-info" style={{ marginBottom: 12 }}>
            {minutes.note}
          </div>
          <div className="card minutes-body">{renderMarkdown(minutes.markdown)}</div>
        </Fragment>
      )}
      {minutes === null && notReady && !canRetry && (
        <p className="section-desc">纪要尚未生成</p>
      )}
    </Fragment>
  )
}
