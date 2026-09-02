/** 试听波形（确认停点与声纹库共用）：条形峰值 + 进度覆盖 + 点击跳转。 */

/** 从整段解码峰值里切出片段的条形波形（48 根柱，0–1 振幅） */
export function clipBars(
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

export function ClipWave({
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
      <g fill="var(--hairline-tertiary)">{rects}</g>
      {progress > 0 && (
        <g fill="var(--primary)" clipPath={`url(#${clipId})`}>
          {rects}
        </g>
      )}
    </svg>
  )
}
