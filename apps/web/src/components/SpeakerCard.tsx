import { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import {
  audioUrl,
  type DecisionKind,
  type ReviewCard,
  type ReviewPerson,
} from '../api/client'
import { Icon } from './Icon'
import { claimPlayback, releasePlayback } from './clipPlayback'

/** 前端的决定草稿：只做体验层拦截，最终合法性以后端为准。 */
export interface DecisionDraft {
  kind: DecisionKind
  display_name?: string
  merge_into_cluster_id?: string
  person_id?: string
}

export function draftValid(draft: DecisionDraft | undefined): boolean {
  if (draft === undefined) {
    return false
  }
  if (draft.kind === 'NEW_PERSON') {
    return (draft.display_name ?? '').trim().length > 0
  }
  if (draft.kind === 'MERGE_WITH_CLUSTER') {
    return (draft.merge_into_cluster_id ?? '') !== ''
  }
  if (draft.kind === 'REASSIGN' || draft.kind === 'LINK_EXISTING') {
    return (draft.person_id ?? '') !== ''
  }
  return true
}

const ANONYMOUS_KINDS = new Set<DecisionKind>(['KEEP_UNKNOWN', 'UNDECIDED_UNKNOWN'])

interface SpeakerCardProps {
  meetingId: string
  card: ReviewCard
  /** 本场其他簇代号，给「与其他说话人合并」选目标用 */
  otherClusterIds: string[]
  /** 全局人员清单，给「换成其他人 / 从声纹库选择」下拉用 */
  people: ReviewPerson[]
  /** 卡片按页面顺序的展示编号（1 起）；保持匿名时转写也以「说话人 N」引用 */
  anonymousIndex: number
  /** 其他簇代号 → 展示编号，给合并下拉显示顺序编号用 */
  clusterLabels: Record<string, number>
  draft: DecisionDraft | undefined
  onChange: (draft: DecisionDraft) => void
}

function formatSeconds(value: number): string {
  const minutes = Math.floor(value / 60)
  const seconds = value - minutes * 60
  return `${minutes}:${seconds.toFixed(1).padStart(4, '0')}`
}

/** 累计时长不需要亚秒精度，向下取整到秒展示（不夸大发言量） */
function formatTotalSeconds(value: number): string {
  const whole = Math.floor(value)
  const minutes = Math.floor(whole / 60)
  const seconds = whole - minutes * 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

/** 从整段解码峰值里切出片段的条形波形（48 根柱，0–1 振幅） */
function clipBars(
  peaks: number[],
  duration: number,
  start: number,
  end: number,
): number[] {
  if (peaks.length === 0 || duration <= 0 || end <= start) {
    return []
  }
  const from = Math.floor((start / duration) * peaks.length)
  const to = Math.max(from + 1, Math.ceil((end / duration) * peaks.length))
  const slice = peaks.slice(from, to)
  const bars: number[] = []
  const BAR_COUNT = 48
  for (let i = 0; i < BAR_COUNT; i += 1) {
    const lo = Math.floor((i / BAR_COUNT) * slice.length)
    const hi = Math.max(lo + 1, Math.floor(((i + 1) / BAR_COUNT) * slice.length))
    let peak = 0
    for (let j = lo; j < hi; j += 1) {
      peak = Math.max(peak, Math.abs(slice[j] ?? 0))
    }
    bars.push(peak)
  }
  return bars
}

function ClipWave({
  bars,
  progress,
  clipId,
  onSeek,
}: {
  bars: number[]
  progress: number
  clipId: string
  onSeek: (ratio: number) => void
}) {
  const rects = bars.map((value, index) => {
    const height = Math.max(2, value * 22)
    return (
      <rect
        key={index}
        x={index * 4}
        y={12 - height / 2}
        width={2}
        height={height}
        rx={1}
      />
    )
  })
  return (
    <svg
      className="clip-wave"
      viewBox="0 0 192 24"
      preserveAspectRatio="none"
      aria-hidden="true"
      onClick={(event) => {
        const rect = event.currentTarget.getBoundingClientRect()
        if (rect.width <= 0) {
          return
        }
        onSeek((event.clientX - rect.left) / rect.width)
      }}
    >
      <defs>
        <clipPath id={clipId}>
          <rect x="0" y="0" width={progress * 192} height="24" />
        </clipPath>
      </defs>
      <g fill="#3e3e44">{rects}</g>
      {progress > 0 && (
        <g fill="#5e6ad2" clipPath={`url(#${clipId})`}>
          {rects}
        </g>
      )}
    </svg>
  )
}

export function SpeakerCard({
  meetingId,
  card,
  otherClusterIds,
  people,
  anonymousIndex,
  clusterLabels,
  draft,
  onChange,
}: SpeakerCardProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const surferRef = useRef<WaveSurfer | null>(null)
  const activeRef = useRef<{ key: string; start: number; end: number } | null>(null)
  // 独占总线里代表本卡的身份；stop 回调只暂停、保留播放头，方便回头续播
  const ownerRef = useRef<symbol | null>(null)
  if (ownerRef.current === null) {
    ownerRef.current = Symbol('speaker-card')
  }
  const owner = ownerRef.current
  const [peaks, setPeaks] = useState<number[] | null>(null)
  const [decodedDuration, setDecodedDuration] = useState(0)
  const [activeKey, setActiveKey] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)

  const pauseFromBus = () => {
    try {
      surferRef.current?.pause()
    } catch {
      // 忽略暂停失败
    }
    setPlaying(false)
  }

  useEffect(() => {
    const container = containerRef.current
    if (container === null) {
      return
    }
    let surfer: WaveSurfer | null = null
    try {
      surfer = WaveSurfer.create({
        container,
        url: audioUrl(meetingId),
        height: 0,
        normalize: true,
        interact: false,
      })
    } catch {
      // 环境不支持（如测试）时静默降级：无波形也能试听与决定
      return
    }
    const ws = surfer
    surferRef.current = ws
    ws.on('decode', () => {
      try {
        // 峰值只用于绘制片段波形；导出失败不影响试听
        const exporter = ws as unknown as {
          exportPeaks?: (options: {
            channels?: number
            maxLength?: number
          }) => number[][]
        }
        const exported = exporter.exportPeaks?.({ channels: 1, maxLength: 2000 })
        const first = exported?.[0]
        if (first !== undefined && first.length > 0) {
          setPeaks(first)
          setDecodedDuration(ws.getDuration())
        }
      } catch {
        // 保持无波形展示
      }
    })
    ws.on('timeupdate', (time: number) => {
      const active = activeRef.current
      if (active === null) {
        return
      }
      const span = active.end - active.start
      setProgress(span > 0 ? Math.min(1, Math.max(0, (time - active.start) / span)) : 0)
      if (time >= active.end) {
        activeRef.current = null
        releasePlayback(owner)
        setActiveKey(null)
        setPlaying(false)
        setProgress(0)
        ws.pause()
      }
    })
    return () => {
      activeRef.current = null
      releasePlayback(owner)
      surferRef.current = null
      ws.destroy()
    }
  }, [meetingId, owner])

  const stopSelf = () => {
    activeRef.current = null
    releasePlayback(owner)
    setActiveKey(null)
    setPlaying(false)
    setProgress(0)
  }

  const toggleClip = (key: string, start: number, end: number) => {
    const ws = surferRef.current
    if (ws === null) {
      return
    }
    if (activeRef.current?.key === key) {
      if (playing) {
        // 暂停保留播放头，再点播放从原位置续播
        releasePlayback(owner)
        setPlaying(false)
        try {
          ws.pause()
        } catch {
          // 忽略暂停失败
        }
        return
      }
      claimPlayback(owner, pauseFromBus)
      setPlaying(true)
      try {
        void ws.play()
      } catch {
        stopSelf()
      }
      return
    }
    claimPlayback(owner, pauseFromBus)
    activeRef.current = { key, start, end }
    setActiveKey(key)
    setPlaying(true)
    setProgress(0)
    try {
      ws.setTime(start)
      void ws.play()
    } catch {
      stopSelf()
    }
  }

  /** 点波形跳到片段内相对位置并从那里播放；点的是别的片段则切换过去 */
  const seekClip = (key: string, start: number, end: number, ratio: number) => {
    const ws = surferRef.current
    if (ws === null) {
      return
    }
    const clamped = Math.min(1, Math.max(0, ratio))
    claimPlayback(owner, pauseFromBus)
    activeRef.current = { key, start, end }
    setActiveKey(key)
    setPlaying(true)
    setProgress(clamped)
    try {
      ws.setTime(start + clamped * (end - start))
      void ws.play()
    } catch {
      stopSelf()
    }
  }

  const setKind = (kind: DecisionKind) => {
    onChange({ kind })
  }

  const anonymousLabel = `保持匿名（标为说话人 ${anonymousIndex}）`
  const options: Array<{ kind: DecisionKind; label: string }> =
    card.suggested_person_id !== null
      ? [
          { kind: 'CONFIRM', label: '确认建议身份' },
          ...(people.length > 0
            ? [{ kind: 'REASSIGN' as DecisionKind, label: '换成其他人' }]
            : []),
          { kind: 'NEAREST_CONFIRMED', label: '并入最近的已确认参会人' },
          { kind: 'KEEP_UNKNOWN', label: anonymousLabel },
        ]
      : [
          { kind: 'NEW_PERSON', label: '新建人' },
          ...(people.length > 0
            ? [{ kind: 'LINK_EXISTING' as DecisionKind, label: '从声纹库选择' }]
            : []),
          { kind: 'MERGE_WITH_CLUSTER', label: '与其他说话人合并' },
          { kind: 'NEAREST_CONFIRMED', label: '并入最近的已确认参会人' },
          { kind: 'UNDECIDED_UNKNOWN', label: anonymousLabel },
        ]

  // 「较高」建议默认选中确认，卡片同时降噪展示：这些卡通常无需用户再判断
  const highSuggestion =
    card.suggested_person_id !== null && card.suggested_tier === 'high'

  return (
    <div
      className={`speaker-card${highSuggestion ? ' suggested-high' : ''}`}
      data-testid={`speaker-card-${card.cluster_id}`}
    >
      <div className="speaker-card-head">
        <span className="speaker-card-name">说话人 {anonymousIndex}</span>
        <span className="speaker-chip">
          {`累计发言 ${formatTotalSeconds(card.total_seconds)}`}
        </span>
        {card.suggested_person_id !== null ? (
          // 建议身份只有「较高 / 需判断」的定性表达，绝不显示百分比；
          // 档位缺失（旧数据）按保守的「需判断」展示
          <span className="speaker-chip suggested">
            建议：{card.suggested_display_name ?? '已知声纹'} ·{' '}
            {card.suggested_tier === 'high' ? '较高' : '需判断'}
          </span>
        ) : (
          <span className="speaker-chip">未识别到已知声纹</span>
        )}
        {draft !== undefined && ANONYMOUS_KINDS.has(draft.kind) && (
          <span className="speaker-chip">将标为：说话人 {anonymousIndex}</span>
        )}
        {draft?.kind === 'NEAREST_CONFIRMED' && (
          <span className="speaker-chip">将按声纹并入最近的已确认参会人</span>
        )}
      </div>

      <div ref={containerRef} style={{ display: 'none' }} />
      <div className="speaker-clips">
        {card.sample_clips.map((clip) => {
          const key = `${clip.start_seconds}-${clip.end_seconds}`
          const active = activeKey === key
          const clipPlaying = active && playing
          const span = clip.end_seconds - clip.start_seconds
          const bars =
            peaks !== null
              ? clipBars(peaks, decodedDuration, clip.start_seconds, clip.end_seconds)
              : []
          const range = `${formatSeconds(clip.start_seconds)}–${formatSeconds(clip.end_seconds)}`
          return (
            <div key={key} className="clip-card">
              <div className="clip-card-row">
                <button
                  type="button"
                  className="clip-play"
                  aria-label={clipPlaying ? `暂停 ${range}` : `试听 ${range}`}
                  onClick={() =>
                    toggleClip(key, clip.start_seconds, clip.end_seconds)
                  }
                >
                  <Icon name={clipPlaying ? 'pause' : 'play'} size={10} />
                </button>
                {bars.length > 0 ? (
                  <ClipWave
                    bars={bars}
                    progress={active ? progress : 0}
                    clipId={`clip-${card.cluster_id}-${key}`}
                    onSeek={(ratio) =>
                      seekClip(key, clip.start_seconds, clip.end_seconds, ratio)
                    }
                  />
                ) : (
                  <span className="clip-wave" />
                )}
                {active && (
                  <span className="clip-elapsed">
                    {`${formatSeconds(progress * span)} / ${formatSeconds(span)}`}
                  </span>
                )}
                <span className="clip-time">{range}</span>
              </div>
              {clip.text !== '' && <div className="clip-text">{clip.text}</div>}
            </div>
          )
        })}
      </div>

      <div
        className="decision-options"
        role="radiogroup"
        aria-label={`说话人 ${anonymousIndex} 的决定`}
      >
        {options.map((option) => (
          <label key={option.kind} className="decision-option">
            <input
              type="radio"
              name={`decision-${card.cluster_id}`}
              checked={draft?.kind === option.kind}
              onChange={() => setKind(option.kind)}
            />
            {option.label}
          </label>
        ))}
      </div>

      {draft?.kind === 'NEW_PERSON' && (
        <div className="decision-extra">
          <input
            className="input"
            placeholder="输入显示名"
            value={draft.display_name ?? ''}
            onChange={(event) =>
              onChange({ kind: 'NEW_PERSON', display_name: event.target.value })
            }
          />
        </div>
      )}

      {(draft?.kind === 'REASSIGN' || draft?.kind === 'LINK_EXISTING') && (
        <div className="decision-extra">
          <select
            className="select"
            aria-label="选择已有人"
            value={draft.person_id ?? ''}
            onChange={(event) =>
              onChange({ kind: draft.kind, person_id: event.target.value })
            }
          >
            <option value="">从声纹库选择</option>
            {people.map((person) => (
              <option key={person.id} value={person.id}>
                {person.display_name}
              </option>
            ))}
          </select>
        </div>
      )}

      {draft?.kind === 'MERGE_WITH_CLUSTER' && (
        <div className="decision-extra">
          <select
            className="select"
            aria-label="合并目标"
            value={draft.merge_into_cluster_id ?? ''}
            onChange={(event) =>
              onChange({
                kind: 'MERGE_WITH_CLUSTER',
                merge_into_cluster_id: event.target.value,
              })
            }
          >
            <option value="">选择合并目标</option>
            {otherClusterIds.map((clusterId) => (
              <option key={clusterId} value={clusterId}>
                说话人 {clusterLabels[clusterId] ?? clusterId}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  )
}
