// 测试用 doctor 响应构造：默认全就绪，按需覆盖字段。

export interface DoctorPayload {
  ffmpeg: boolean
  models: { asr: boolean; segmentation: boolean; embedding: boolean }
  cli: {
    claude_available: boolean
    claude_logged_in: boolean
    codex_available: boolean
    codex_logged_in: boolean
  }
  disk_gb_free: number
  transcription_ready: boolean
  minutes_ready: boolean
}

export function makeDoctorReport(overrides: Partial<DoctorPayload> = {}): DoctorPayload {
  return {
    ffmpeg: true,
    models: { asr: true, segmentation: true, embedding: true },
    cli: {
      claude_available: true,
      claude_logged_in: true,
      codex_available: true,
      codex_logged_in: true,
    },
    disk_gb_free: 128.5,
    transcription_ready: true,
    minutes_ready: true,
    ...overrides,
  }
}
