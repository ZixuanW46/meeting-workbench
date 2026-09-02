import { useEffect, useRef, useState } from 'react'
import { eventsUrl, getProgress, type ProgressSnapshot } from '../api/client'
import { PIPELINE_STEPS, stateLabel } from '../labels'
import { Icon } from './Icon'

const POLL_INTERVAL_MS = 3000

interface ProgressProps {
  meetingId: string
  /** 每收到一次进度快照回调一次；父组件用它在状态变化时刷新会议详情。 */
  onSnapshot?: (snapshot: ProgressSnapshot) => void
}

export function Progress({ meetingId, onSnapshot }: ProgressProps) {
  const [snapshot, setSnapshot] = useState<ProgressSnapshot | null>(null)
  const [degraded, setDegraded] = useState(false)
  const onSnapshotRef = useRef(onSnapshot)
  onSnapshotRef.current = onSnapshot

  useEffect(() => {
    let stopped = false
    let timer: number | null = null
    let source: EventSource | null = null

    const apply = (next: ProgressSnapshot) => {
      if (stopped) {
        return
      }
      // seq 单调递增；乱序到达的旧快照直接丢弃
      setSnapshot((prev) => (prev !== null && prev.seq >= next.seq ? prev : next))
      onSnapshotRef.current?.(next)
    }

    const startPolling = () => {
      if (timer !== null) {
        return
      }
      setDegraded(true)
      timer = window.setInterval(() => {
        getProgress(meetingId)
          .then(apply)
          .catch(() => {
            // 单次轮询失败静默，下一轮再试
          })
      }, POLL_INTERVAL_MS)
    }

    // jsdom / 老环境没有 EventSource 时直接走轮询
    const EventSourceImpl: typeof EventSource | undefined = window.EventSource
    if (EventSourceImpl !== undefined) {
      source = new EventSourceImpl(eventsUrl(meetingId))
      source.onmessage = (event) => {
        try {
          apply(JSON.parse(event.data) as ProgressSnapshot)
        } catch {
          // 忽略坏事件（如 keep-alive 注释不会走到这里）
        }
      }
      source.onerror = () => {
        // SSE 断开：关掉连接，落到 3 秒轮询兜底
        source?.close()
        startPolling()
      }
    } else {
      startPolling()
    }

    return () => {
      stopped = true
      source?.close()
      if (timer !== null) {
        window.clearInterval(timer)
      }
    }
  }, [meetingId])

  const currentStep = snapshot?.processing_step ?? null
  const currentIndex = PIPELINE_STEPS.findIndex((step) => step.key === currentStep)
  const state = snapshot?.state ?? null
  // 排队中还没有步骤：给一句解释，别让人以为卡住了
  const subtitle =
    snapshot === null
      ? '正在连接进度…'
      : state === 'QUEUED'
        ? '等待前面的会议处理完成；模型在本机串行运行'
        : state === 'GENERATING_MINUTES'
          ? '逐字稿正交给本机 CLI 清洗并生成纪要，长会议需要几分钟'
          : '音频只在本机处理，转写与切分期间可以先离开这个页面'

  return (
    <div className="progress-hero" role="status" aria-live="polite">
      <span className="progress-hero-ring" aria-hidden="true" />
      <div className="progress-hero-state">
        {snapshot === null ? '连接进度…' : stateLabel(snapshot.state)}
      </div>
      <div className="progress-hero-subtitle">{subtitle}</div>
      <ol className="progress-steps">
        {PIPELINE_STEPS.map((step, index) => {
          const done = currentIndex >= 0 && index < currentIndex
          const current = currentIndex >= 0 && index === currentIndex
          const tone = done ? 'done' : current ? 'current' : 'pending'
          return (
            <li
              key={step.key}
              className={`progress-step progress-step-${tone}`}
              aria-current={current ? 'step' : undefined}
            >
              <span className="progress-step-dot" aria-hidden="true">
                {done && <Icon name="check" size={10} />}
              </span>
              <span className="progress-step-label">
                {step.label}
                {current && snapshot?.detail ? ` ${snapshot.detail}` : ''}
              </span>
            </li>
          )
        })}
      </ol>
      {degraded && (
        <span className="progress-degraded">实时连接已断开，每 3 秒自动刷新</span>
      )}
    </div>
  )
}
