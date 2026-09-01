import { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import { voiceprintAudioUrl } from '../api/client'
import { ClipWave, clipBars } from './ClipWave'
import { claimPlayback, releasePlayback } from './clipPlayback'
import { Icon } from './Icon'

/** 声纹模板试听：波形点击跳转、实时进度，走全局独占总线（同刻只播一条）。 */
export function VoiceprintClip({
  voiceprintId,
  ownerName,
}: {
  voiceprintId: string
  ownerName: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const surferRef = useRef<WaveSurfer | null>(null)
  const ownerRef = useRef<symbol | null>(null)
  if (ownerRef.current === null) {
    ownerRef.current = Symbol('voiceprint-clip')
  }
  const owner = ownerRef.current
  const [bars, setBars] = useState<number[]>([])
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    const container = containerRef.current
    if (container === null) {
      return
    }
    let surfer: WaveSurfer | null = null
    try {
      surfer = WaveSurfer.create({
        container,
        url: voiceprintAudioUrl(voiceprintId),
        height: 0,
        normalize: true,
        interact: false,
      })
    } catch {
      // 环境不支持（如测试）时静默降级：无波形也能删除模板
      return
    }
    const ws = surfer
    surferRef.current = ws
    ws.on('decode', () => {
      try {
        const exporter = ws as unknown as {
          exportPeaks?: (options: {
            channels?: number
            maxLength?: number
          }) => number[][]
        }
        const first = exporter.exportPeaks?.({ channels: 1, maxLength: 400 })?.[0]
        const duration = ws.getDuration()
        if (first !== undefined && first.length > 0 && duration > 0) {
          setBars(clipBars(first, duration, 0, duration))
        }
      } catch {
        // 保持无波形展示
      }
    })
    ws.on('timeupdate', (time: number) => {
      const duration = ws.getDuration()
      if (duration > 0) {
        setProgress(Math.min(1, Math.max(0, time / duration)))
      }
    })
    ws.on('finish', () => {
      setPlaying(false)
      setProgress(0)
      releasePlayback(owner)
    })
    return () => {
      releasePlayback(owner)
      surferRef.current = null
      ws.destroy()
    }
  }, [voiceprintId, owner])

  const pauseFromBus = () => {
    try {
      surferRef.current?.pause()
    } catch {
      // 忽略暂停失败
    }
    setPlaying(false)
  }

  const startPlaying = () => {
    const ws = surferRef.current
    if (ws === null) {
      return
    }
    claimPlayback(owner, pauseFromBus)
    try {
      void ws.play()
      setPlaying(true)
    } catch {
      setPlaying(false)
      releasePlayback(owner)
    }
  }

  const toggle = () => {
    if (playing) {
      pauseFromBus()
      releasePlayback(owner)
      return
    }
    startPlaying()
  }

  const seek = (ratio: number) => {
    const ws = surferRef.current
    if (ws === null) {
      return
    }
    const duration = ws.getDuration()
    if (duration <= 0) {
      return
    }
    try {
      ws.setTime(ratio * duration)
      setProgress(ratio)
    } catch {
      return
    }
    if (!playing) {
      startPlaying()
    }
  }

  return (
    <>
      <div ref={containerRef} style={{ display: 'none' }} />
      <button
        type="button"
        className="clip-play"
        aria-label={
          playing ? `暂停 ${ownerName} 的模板试听` : `试听 ${ownerName} 的模板`
        }
        onClick={toggle}
      >
        <Icon name={playing ? 'pause' : 'play'} size={10} />
      </button>
      {bars.length > 0 ? (
        <ClipWave
          bars={bars}
          progress={progress}
          clipId={`vp-${voiceprintId}`}
          onSeek={seek}
        />
      ) : (
        <span className="clip-wave" />
      )}
    </>
  )
}
