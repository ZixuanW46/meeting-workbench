import { useEffect, useRef } from 'react'
import WaveSurfer from 'wavesurfer.js'
import { audioUrl, type DecisionKind, type ReviewCard } from '../api/client'
import { Icon } from './Icon'

/** 前端的决定草稿：只做体验层拦截，最终合法性以后端为准。 */
export interface DecisionDraft {
  kind: DecisionKind
  display_name?: string
  merge_into_cluster_id?: string
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
  return true
}

interface SpeakerCardProps {
  meetingId: string
  card: ReviewCard
  /** 本场其他簇代号，给「与其他说话人合并」选目标用 */
  otherClusterIds: string[]
  draft: DecisionDraft | undefined
  onChange: (draft: DecisionDraft) => void
}

function formatSeconds(value: number): string {
  const minutes = Math.floor(value / 60)
  const seconds = value - minutes * 60
  return `${minutes}:${seconds.toFixed(1).padStart(4, '0')}`
}

export function SpeakerCard({
  meetingId,
  card,
  otherClusterIds,
  draft,
  onChange,
}: SpeakerCardProps) {
  const waveformRef = useRef<HTMLDivElement>(null)
  const playClipRef = useRef<(start: number, end: number) => void>(() => {})

  useEffect(() => {
    const container = waveformRef.current
    if (container === null) {
      return
    }
    let surfer: WaveSurfer | null = null
    try {
      surfer = WaveSurfer.create({
        container,
        url: audioUrl(meetingId),
        height: 36,
        waveColor: '#d4d5db',
        progressColor: '#5e6ad2',
        cursorColor: '#5e6ad2',
        cursorWidth: 1,
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        normalize: true,
        interact: false,
      })
    } catch {
      // 环境不支持（如测试）时静默降级：无波形也能做决定
      return
    }
    const ws = surfer
    let stopAt: number | null = null
    ws.on('timeupdate', (time: number) => {
      if (stopAt !== null && time >= stopAt) {
        stopAt = null
        ws.pause()
      }
    })
    playClipRef.current = (start, end) => {
      try {
        stopAt = end
        ws.setTime(start)
        void ws.play()
      } catch {
        stopAt = null
      }
    }
    return () => {
      playClipRef.current = () => {}
      ws.destroy()
    }
  }, [meetingId])

  const setKind = (kind: DecisionKind) => {
    onChange({ kind })
  }

  const options: Array<{ kind: DecisionKind; label: string }> =
    card.suggested_person_id !== null
      ? [
          { kind: 'CONFIRM', label: '确认建议身份' },
          { kind: 'KEEP_UNKNOWN', label: '保持未知' },
        ]
      : [
          { kind: 'NEW_PERSON', label: '新建人' },
          { kind: 'MERGE_WITH_CLUSTER', label: '与其他说话人合并' },
          { kind: 'UNDECIDED_UNKNOWN', label: '暂不确定' },
        ]

  return (
    <div className="speaker-card" data-testid={`speaker-card-${card.cluster_id}`}>
      <div className="speaker-card-head">
        <span className="speaker-card-name">说话人 {card.cluster_id}</span>
        {card.suggested_person_id !== null ? (
          // 建议身份只有「较高 / 需判断」的定性表达，绝不显示百分比
          <span className="speaker-chip suggested">有建议身份 · 需判断</span>
        ) : (
          <span className="speaker-chip">未识别到已知声纹</span>
        )}
      </div>

      <div ref={waveformRef} className="waveform" />
      <div className="clip-row">
        <span className="form-hint">试听片段</span>
        {card.sample_clips.map((clip) => (
          <button
            key={`${clip.start_seconds}-${clip.end_seconds}`}
            type="button"
            className="clip-btn"
            onClick={() => playClipRef.current(clip.start_seconds, clip.end_seconds)}
          >
            <Icon name="play" size={10} />
            {formatSeconds(clip.start_seconds)}–{formatSeconds(clip.end_seconds)}
          </button>
        ))}
      </div>

      {card.text !== '' && <div className="speaker-text">{card.text}</div>}

      <div className="decision-options" role="radiogroup" aria-label={`说话人 ${card.cluster_id} 的决定`}>
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
                说话人 {clusterId}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  )
}
