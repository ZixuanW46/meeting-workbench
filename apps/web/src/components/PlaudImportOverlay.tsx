import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import type { PlaudImportPhase } from '../api/client'
import { formatDuration } from './PlaudRecordingPicker'

/** 均衡器条数：奇数条居中最稳，7 条在 96px 的环里还留得住呼吸空间 */
const BAR_COUNT = 7

const MB = 1024 * 1024

/** 字节 → 「126.5 MB」；导入的都是几十上百 MB 的音频，统一到 MB 一位小数最好读 */
export function formatMegabytes(bytes: number): string {
  const mb = Math.max(0, bytes) / MB
  return `${mb.toFixed(1)} MB`
}

/** 已下载/总字节 → 0～100 的整数；向下取整，别让 99.7% 提前显示成 100% */
export function progressPercent(bytesDone: number, bytesTotal: number | null): number | null {
  if (bytesTotal === null || bytesTotal <= 0) {
    return null
  }
  const ratio = Math.max(0, bytesDone) / bytesTotal
  return Math.min(100, Math.floor(ratio * 100))
}

/** 阶段文案：进度还没登记（phase 为 null）时按「正在取直链」说，别让人以为卡住了 */
export function phaseLabel(phase: PlaudImportPhase | null): string {
  switch (phase) {
    case 'downloading':
      return '正在下载录音…'
    case 'finalizing':
      return '下载完成，正在排队处理…'
    case 'done':
      return '导入完成，正在打开工作台…'
    case 'failed':
      return '导入失败'
    default:
      return '正在向 Plaud 取音频直链…'
  }
}

interface PlaudImportOverlayProps {
  /** 后端进度还没登记时传 null，按 resolving 展示 */
  phase: PlaudImportPhase | null
  bytesDone: number
  bytesTotal: number | null
  recordingName: string
  recordingDurationMs: number
}

/**
 * 导入时的全屏遮罩：POST /api/plaud/import 是同步下载，一小时的录音要等几十秒，
 * 这段时间页面不能只剩一行小字。环 + 均衡器给「在动」的实感，进度条给确定的预期。
 */
export function PlaudImportOverlay({
  phase,
  bytesDone,
  bytesTotal,
  recordingName,
  recordingDurationMs,
}: PlaudImportOverlayProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null)

  // 焦点收进遮罩：底下的表单已被盖住，Tab 不该还能走到看不见的控件上
  useEffect(() => {
    dialogRef.current?.focus()
  }, [])

  const percent = progressPercent(bytesDone, bytesTotal)
  // 确定态只在真的在下载、且知道总大小时才给；取直链/排队阶段一律走不确定态
  const determinate = percent !== null && (phase === 'downloading' || phase === 'done')

  return createPortal(
    <div
      className="import-overlay"
      role="dialog"
      aria-modal="true"
      aria-busy="true"
      aria-label="正在从 Plaud 导入录音"
      tabIndex={-1}
      ref={dialogRef}
    >
      <div className="import-overlay-panel">
        <div className="import-pulse" aria-hidden="true">
          <span className="import-pulse-ring" />
          <span className="import-pulse-bars">
            {Array.from({ length: BAR_COUNT }, (_, index) => (
              <span
                key={index}
                className="import-pulse-bar"
                style={{ animationDelay: `${index * 0.11}s` }}
              />
            ))}
          </span>
        </div>

        <div className="import-overlay-phase">{phaseLabel(phase)}</div>
        <div className="import-overlay-name">
          <span className="import-overlay-recording">{recordingName}</span>
          <span className="import-overlay-dot">·</span>
          <span>{formatDuration(recordingDurationMs)}</span>
        </div>

        <div
          className={`import-overlay-track${determinate ? '' : ' indeterminate'}`}
          role="progressbar"
          aria-label="下载进度"
          {...(determinate
            ? { 'aria-valuenow': percent, 'aria-valuemin': 0, 'aria-valuemax': 100 }
            : {})}
        >
          <span
            className="import-overlay-fill"
            style={determinate ? { width: `${percent}%` } : undefined}
          />
        </div>

        <div className="import-overlay-meter">
          {determinate ? (
            <>
              <span className="import-overlay-percent">{percent}%</span>
              <span className="import-overlay-bytes">
                {formatMegabytes(bytesDone)} / {formatMegabytes(bytesTotal ?? 0)}
              </span>
            </>
          ) : (
            <span className="import-overlay-bytes">
              {phase === 'downloading' && bytesDone > 0
                ? `已下载 ${formatMegabytes(bytesDone)}`
                : '正在建立连接…'}
            </span>
          )}
        </div>

        <div className="import-overlay-hint">请勿关闭页面</div>
      </div>
    </div>,
    document.body,
  )
}
