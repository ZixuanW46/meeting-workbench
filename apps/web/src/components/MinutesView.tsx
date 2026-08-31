import { Fragment, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
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

// 纪要由本机 LLM 产出，构件不可控（粗体、嵌套列表、checkbox、表格都可能
// 出现），交给 react-markdown + GFM 完整渲染，避免把标记符号漏给用户。
function renderMarkdown(markdown: string) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
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
