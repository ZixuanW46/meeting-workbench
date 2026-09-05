import { useCallback, useEffect, useState } from 'react'
import {
  formatApiError,
  getPlaudStatus,
  listPlaudRecordings,
  plaudLogin,
  type PlaudRecording,
  type PlaudStatus,
} from '../api/client'
import { Icon } from './Icon'
import { SkeletonListRows } from './Skeleton'
import { toast } from './Toast'

/** 搜索防抖：打字停 300ms 才走服务端，避免每敲一下起一次 MCP 进程 */
const SEARCH_DEBOUNCE_MS = 300

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** 录音开始时间（带时区的 ISO）→ 观看者本地时区的 YYYY-MM-DD */
export function recordingLocalDate(startedAt: string): string {
  const date = new Date(startedAt)
  if (Number.isNaN(date.getTime())) {
    return ''
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** 录音开始时间 → 本地 YYYY-MM-DD HH:mm；解析不了就照原样显示 */
export function formatRecordingTime(startedAt: string): string {
  const date = new Date(startedAt)
  if (Number.isNaN(date.getTime())) {
    return startedAt
  }
  return `${recordingLocalDate(startedAt)} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 时长排版：满一小时只到分（1h27m），不足一小时给到秒（5m12s / 14s） */
export function formatDuration(durationMs: number): string {
  const totalSeconds = Math.max(0, Math.round(durationMs / 1000))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) {
    return `${hours}h${minutes}m`
  }
  if (minutes > 0) {
    return `${minutes}m${seconds}s`
  }
  return `${seconds}s`
}

interface PlaudRecordingPickerProps {
  value: PlaudRecording | null
  onChange: (recording: PlaudRecording) => void
}

/**
 * 从 Plaud 云端挑一条录音：先看 MCP 是否装好、是否登录，就绪后才列录音。
 * 已经导入过的录音只给一条去工作台的出口，不再让人重复导入。
 */
export function PlaudRecordingPicker({ value, onChange }: PlaudRecordingPickerProps) {
  const [status, setStatus] = useState<PlaudStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [loggingIn, setLoggingIn] = useState(false)
  const [loginError, setLoginError] = useState<string | null>(null)
  // query 是输入框里的字，activeQuery 是防抖后真正请求用的字
  const [query, setQuery] = useState('')
  const [activeQuery, setActiveQuery] = useState('')
  const [items, setItems] = useState<PlaudRecording[] | null>(null)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [filtered, setFiltered] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  // 「重试」靠它把加载 effect 再跑一遍
  const [reloadToken, setReloadToken] = useState(0)

  const refreshStatus = useCallback(async () => {
    setStatusError(null)
    try {
      setStatus(await getPlaudStatus())
    } catch (e: unknown) {
      setStatusError(formatApiError(e))
    }
  }, [])

  useEffect(() => {
    void refreshStatus()
  }, [refreshStatus])

  useEffect(() => {
    if (query === activeQuery) {
      return
    }
    const timer = window.setTimeout(() => setActiveQuery(query), SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [query, activeQuery])

  const loggedIn = status?.logged_in === true

  useEffect(() => {
    if (!loggedIn) {
      return
    }
    let stale = false
    setItems(null)
    setListError(null)
    listPlaudRecordings({ page: 1, ...(activeQuery.trim() !== '' ? { query: activeQuery } : {}) })
      .then((result) => {
        if (stale) {
          return
        }
        setItems(result.items)
        setPage(result.page)
        setHasMore(result.has_more)
        setFiltered(result.filtered)
      })
      .catch((e: unknown) => {
        if (!stale) {
          setListError(formatApiError(e))
        }
      })
    return () => {
      stale = true
    }
  }, [loggedIn, activeQuery, reloadToken])

  const onLogin = () => {
    setLoggingIn(true)
    setLoginError(null)
    plaudLogin()
      .then(async (result) => {
        if (result.logged_in) {
          toast('已登录 Plaud')
        } else {
          setLoginError(result.message)
        }
        await refreshStatus()
      })
      .catch((e: unknown) => {
        setLoginError(formatApiError(e))
      })
      .finally(() => {
        setLoggingIn(false)
      })
  }

  const onLoadMore = () => {
    setLoadingMore(true)
    setListError(null)
    listPlaudRecordings({
      page: page + 1,
      ...(activeQuery.trim() !== '' ? { query: activeQuery } : {}),
    })
      .then((result) => {
        setItems((current) => [...(current ?? []), ...result.items])
        setPage(result.page)
        setHasMore(result.has_more)
      })
      .catch((e: unknown) => {
        setListError(formatApiError(e))
      })
      .finally(() => {
        setLoadingMore(false)
      })
  }

  if (statusError !== null) {
    return (
      <div className="plaud-picker">
        <div className="notice notice-error">
          <span>{statusError}</span>
          <button type="button" className="btn btn-ghost" onClick={() => void refreshStatus()}>
            重试
          </button>
        </div>
      </div>
    )
  }

  if (status === null) {
    return (
      <div className="plaud-picker">
        <SkeletonListRows rows={3} />
      </div>
    )
  }

  if (!status.available) {
    return (
      <div className="plaud-picker">
        <div className="notice notice-warn">
          <span className="plaud-notice-body">
            <span>{status.message ?? 'Plaud MCP 未安装，装好后就能直接导入云端录音'}</span>
            <span className="plaud-install">
              在 Mac mini 上执行 <code>npm install -g @plaud-ai/mcp</code>
            </span>
          </span>
        </div>
      </div>
    )
  }

  if (!status.logged_in) {
    return (
      <div className="plaud-picker">
        <div className="notice notice-warn">
          <span>{status.message ?? 'Plaud 未登录，请先登录'}</span>
        </div>
        <div className="plaud-login">
          <button type="button" className="btn" disabled={loggingIn} onClick={onLogin}>
            <Icon name="cloud" size={12} />
            登录 Plaud
          </button>
          {loggingIn && (
            <span className="form-hint">已在 Mac mini 上打开浏览器，请在 2 分钟内完成授权…</span>
          )}
        </div>
        {loginError !== null && <div className="notice notice-error">{loginError}</div>}
      </div>
    )
  }

  const account = status.user?.nickname ?? status.user?.email ?? null

  return (
    <div className="plaud-picker">
      <div className="plaud-toolbar">
        <input
          className="input plaud-search"
          type="search"
          aria-label="按录音名称搜索"
          placeholder="按录音名称搜索"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            // 选择器嵌在新建会议表单里：回车只该是「搜完了」，不能顺手提交表单
            if (event.key === 'Enter') {
              event.preventDefault()
            }
          }}
        />
        {account !== null && <span className="plaud-account">{account}</span>}
      </div>

      {listError !== null && (
        <div className="notice notice-error">
          <span>{listError}</span>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setReloadToken((token) => token + 1)}
          >
            重试
          </button>
        </div>
      )}

      {items === null && listError === null && <SkeletonListRows rows={3} />}

      {items !== null && items.length === 0 && (
        <div className="list-card">
          <div className="empty">
            <div className="empty-title">
              {filtered ? '没有匹配的录音' : 'Plaud 里还没有录音'}
            </div>
            <div>{filtered ? '换个关键词再找找' : '先用 Plaud 录一段，再回来导入'}</div>
          </div>
        </div>
      )}

      {items !== null && items.length > 0 && (
        <div className="list-card plaud-list" role="radiogroup" aria-label="Plaud 录音">
          {items.map((recording) => {
            const meta = `${formatRecordingTime(recording.started_at)} · ${formatDuration(recording.duration_ms)}`
            if (recording.imported_meeting_id !== null) {
              return (
                <div key={recording.file_id} className="list-row plaud-row-imported">
                  <span className="list-row-main">
                    <span className="list-row-title">{recording.name}</span>
                    <span className="list-row-meta">{meta}</span>
                  </span>
                  <span className="badge-lang">已导入</span>
                  <a
                    className="btn btn-ghost"
                    href={`#/meetings/${recording.imported_meeting_id}`}
                  >
                    打开
                  </a>
                </div>
              )
            }
            const selected = value?.file_id === recording.file_id
            return (
              <button
                key={recording.file_id}
                type="button"
                role="radio"
                aria-checked={selected}
                className={`list-row plaud-row${selected ? ' selected' : ''}`}
                onClick={() => onChange(recording)}
              >
                <span className="list-row-main">
                  <span className="list-row-title">{recording.name}</span>
                  <span className="list-row-meta">{meta}</span>
                </span>
                {selected && <Icon name="check" size={13} className="plaud-row-check" />}
              </button>
            )
          })}
        </div>
      )}

      {items !== null && items.length > 0 && hasMore && !filtered && (
        <button
          type="button"
          className="btn btn-ghost plaud-more"
          disabled={loadingMore}
          onClick={onLoadMore}
        >
          加载更多
        </button>
      )}
    </div>
  )
}
