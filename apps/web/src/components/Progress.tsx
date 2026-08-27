import { useEffect, useRef, useState } from 'react'
import { eventsUrl, getProgress, type ProgressSnapshot } from '../api/client'
import { PIPELINE_STEPS, STEP_LABELS, stateLabel } from '../labels'

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

  return (
    <div className="progress-panel">
      <div className="progress-current">
        <span className="spinner" aria-hidden="true" />
        <span className="progress-state">
          {snapshot === null ? '连接进度…' : stateLabel(snapshot.state)}
        </span>
        {currentStep !== null && (
          <span className="progress-step-label">
            {STEP_LABELS[currentStep] ?? currentStep}
          </span>
        )}
      </div>
      <div className="progress-track" aria-hidden="true">
        {PIPELINE_STEPS.map((step, index) => {
          // 已过步骤实心、当前步骤实心且轻微呼吸
          const filled = currentIndex >= 0 && index <= currentIndex
          const current = currentIndex >= 0 && index === currentIndex
          return (
            <span
              key={step.key}
              title={step.label}
              className={`progress-seg${filled ? ' filled' : ''}${current ? ' current' : ''}`}
            />
          )
        })}
      </div>
      {degraded && (
        <span className="progress-degraded">实时连接已断开，每 3 秒自动刷新</span>
      )}
    </div>
  )
}
