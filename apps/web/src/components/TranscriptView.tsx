import { useEffect, useRef, useState } from 'react'
import {
  audioUrl,
  formatApiError,
  getTranscript,
  type TranscriptBlock,
  type TranscriptResult,
  type TranscriptVariant,
} from '../api/client'
import { claimPlayback, releasePlayback } from './clipPlayback'
import { Icon } from './Icon'

interface TranscriptRow {
  time: string
  speaker: string
  text: string
  startSeconds: number
  endSeconds: number
}

/** 秒 → mm:ss，超一小时 h:mm:ss；与后端导出口径一致 */
export function formatClock(seconds: number): string {
  const total = Math.floor(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const rest = total % 60
  const mmss = `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
  return hours > 0 ? `${hours}:${mmss}` : mmss
}

function toRows(blocks: TranscriptBlock[], variant: TranscriptVariant): TranscriptRow[] {
  return blocks.map((block) => ({
    time: `${formatClock(block.start_seconds)} – ${formatClock(block.end_seconds)}`,
    speaker: block.label,
    // 清洗口径下单块没有清洗文本就回退原文，其余块不受影响
    text:
      variant === 'cleaned' && block.cleaned_text !== null ? block.cleaned_text : block.text,
    startSeconds: block.start_seconds,
    endSeconds: block.end_seconds,
  }))
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
  // 整页共享一个 audio 元素回听会议原声；行级只做 seek + 到点自停。
  const audioRef = useRef<HTMLAudioElement>(null)
  const ownerRef = useRef<symbol | null>(null)
  if (ownerRef.current === null) {
    ownerRef.current = Symbol('transcript-block')
  }
  const owner = ownerRef.current
  const [playingIndex, setPlayingIndex] = useState<number | null>(null)
  const playingRef = useRef<{ index: number; endSeconds: number } | null>(null)

  useEffect(() => {
    let stale = false
    getTranscript(meetingId)
      .then((data) => {
        if (!stale) {
          setTranscript(data)
          onCleanedAvailable?.(data.cleaned_available)
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

  useEffect(() => {
    return () => {
      releasePlayback(owner)
    }
  }, [owner])

  const stopPlayback = () => {
    try {
      audioRef.current?.pause()
    } catch {
      // 暂停失败不阻塞状态复位
    }
    playingRef.current = null
    setPlayingIndex(null)
  }

  const playRow = (index: number, row: TranscriptRow) => {
    const audio = audioRef.current
    if (audio === null) {
      return
    }
    claimPlayback(owner, stopPlayback)
    playingRef.current = { index, endSeconds: row.endSeconds }
    setPlayingIndex(index)

    const begin = () => {
      // 等元数据期间用户可能已暂停或切到别行：意图不在本行就不开播。
      if (playingRef.current?.index !== index) {
        return
      }
      try {
        audio.currentTime = row.startSeconds
        const started = audio.play()
        if (started !== undefined) {
          started.catch(() => {
            stopPlayback()
            releasePlayback(owner)
          })
        }
      } catch {
        stopPlayback()
        releasePlayback(owner)
      }
    }
    // 元数据未就绪时先触发加载，seek 要等 loadedmetadata 才可靠。
    if (audio.readyState >= 1) {
      begin()
    } else {
      audio.addEventListener('loadedmetadata', begin, { once: true })
      try {
        audio.load()
      } catch {
        // 加载失败由 play 的失败路径兜底
      }
    }
  }

  const toggleRow = (index: number, row: TranscriptRow) => {
    if (playingIndex === index) {
      stopPlayback()
      releasePlayback(owner)
      return
    }
    playRow(index, row)
  }

  const handleTimeUpdate = () => {
    const playing = playingRef.current
    const audio = audioRef.current
    if (playing === null || audio === null) {
      return
    }
    if (audio.currentTime >= playing.endSeconds) {
      stopPlayback()
      releasePlayback(owner)
    }
  }

  if (error !== null) {
    return <div className="notice notice-error">{error}</div>
  }
  if (transcript === null) {
    return <p className="section-desc">加载转写…</p>
  }

  const rows = toRows(transcript.blocks, variant)
  if (rows.length === 0) {
    return <p className="section-desc">本场会议没有逐字稿</p>
  }
  return (
    <div className="card">
      {rows.map((row, index) => (
        <div key={index} className="transcript-row">
          <button
            type="button"
            className="clip-play transcript-play"
            aria-label={
              playingIndex === index
                ? `暂停 ${row.time} 原声`
                : `播放 ${row.time} 原声`
            }
            onClick={() => toggleRow(index, row)}
          >
            <Icon name={playingIndex === index ? 'pause' : 'play'} size={9} />
          </button>
          <span className="transcript-time">{row.time}</span>
          <span className="transcript-speaker">{row.speaker}</span>
          <span className="transcript-text">{row.text}</span>
        </div>
      ))}
      {/* 隐藏元素放行列表之后：首行仍是 first-child，别抢掉它的去上边线规则 */}
      <audio
        ref={audioRef}
        src={audioUrl(meetingId)}
        preload="none"
        data-testid="transcript-audio"
        onTimeUpdate={handleTimeUpdate}
        onEnded={() => {
          stopPlayback()
          releasePlayback(owner)
        }}
      />
    </div>
  )
}
