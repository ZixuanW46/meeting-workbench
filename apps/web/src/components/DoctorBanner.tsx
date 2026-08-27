import { useEffect, useState } from 'react'
import { getDoctor, type DoctorReport } from '../api/client'

// 关闭只记本次会话（sessionStorage）：刷新标签页后若仍未就绪会再次提示
const DISMISS_KEYS = {
  transcription: 'mw:doctor-dismissed:transcription',
  minutes: 'mw:doctor-dismissed:minutes',
} as const

type BannerKind = keyof typeof DISMISS_KEYS

function readDismissed(kind: BannerKind): boolean {
  try {
    return sessionStorage.getItem(DISMISS_KEYS[kind]) === '1'
  } catch {
    return false
  }
}

function storeDismissed(kind: BannerKind): void {
  try {
    sessionStorage.setItem(DISMISS_KEYS[kind], '1')
  } catch {
    // 存储不可用时仅本次渲染内生效
  }
}

function missingTranscriptionParts(report: DoctorReport): string[] {
  const parts: string[] = []
  if (!report.ffmpeg) {
    parts.push('ffmpeg')
  }
  if (!report.models.asr) {
    parts.push('ASR 模型')
  }
  if (!report.models.segmentation) {
    parts.push('切分模型')
  }
  if (!report.models.embedding) {
    parts.push('声纹模型')
  }
  return parts
}

/** 就绪横幅：转写未就绪红条、纪要 CLI 未就绪黄条；探测失败静默。 */
export function DoctorBanner() {
  const [report, setReport] = useState<DoctorReport | null>(null)
  const [dismissed, setDismissed] = useState<Record<BannerKind, boolean>>(() => ({
    transcription: readDismissed('transcription'),
    minutes: readDismissed('minutes'),
  }))

  useEffect(() => {
    let stale = false
    getDoctor()
      .then((data) => {
        if (!stale) {
          setReport(data)
        }
      })
      .catch(() => {
        // 探测失败不打扰使用：不渲染横幅
      })
    return () => {
      stale = true
    }
  }, [])

  if (report === null) {
    return null
  }

  const dismiss = (kind: BannerKind) => {
    storeDismissed(kind)
    setDismissed((prev) => ({ ...prev, [kind]: true }))
  }

  const showTranscription = !report.transcription_ready && !dismissed.transcription
  const showMinutes = !report.minutes_ready && !dismissed.minutes
  if (!showTranscription && !showMinutes) {
    return null
  }

  const missing = missingTranscriptionParts(report)

  return (
    <div className="doctor-banners">
      {showTranscription && (
        <div className="notice notice-error doctor-banner">
          <span>
            转写暂不可用
            {missing.length > 0 ? `：缺少 ${missing.join('、')}` : ''}
            。请运行 ./scripts/doctor.sh 查看安装步骤；仍可新建会议并上传录音。
          </span>
          <button
            type="button"
            className="notice-close"
            aria-label="关闭转写提示"
            onClick={() => dismiss('transcription')}
          >
            ×
          </button>
        </div>
      )}
      {showMinutes && (
        <div className="notice notice-warn doctor-banner">
          <span>
            纪要暂不可用：生成纪要需要本机安装并登录 claude 或 codex
            CLI；转写不受影响，仍可正常使用。
          </span>
          <button
            type="button"
            className="notice-close"
            aria-label="关闭纪要提示"
            onClick={() => dismiss('minutes')}
          >
            ×
          </button>
        </div>
      )}
    </div>
  )
}
