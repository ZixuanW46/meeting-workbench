// 状态与处理步骤的用户可见文案（中文），全站统一从这里取。

export const STATE_LABELS: Record<string, string> = {
  DRAFT: '待上传',
  UPLOADING: '上传中',
  QUEUED: '排队中',
  PROCESSING: '处理中',
  AWAITING_SPEAKER_REVIEW: '待确认说话人',
  APPLYING_DECISIONS: '应用决定中',
  GENERATING_MINUTES: '生成纪要中',
  READY: '已完成',
  PARTIAL_READY: '纪要待重试',
  FAILED: '处理失败',
  CANCELED: '已取消',
}

export const STEP_LABELS: Record<string, string> = {
  VALIDATING: '校验音频',
  ASR: '语音转写',
  DIARIZATION: '说话人切分',
  VOICEPRINT_MATCHING: '声纹匹配',
  PREPARING_REVIEW: '准备确认包',
  GENERATING_MINUTES: '生成纪要',
}

export const PIPELINE_STEPS: Array<{ key: string; label: string }> = [
  { key: 'VALIDATING', label: STEP_LABELS.VALIDATING },
  { key: 'ASR', label: STEP_LABELS.ASR },
  { key: 'DIARIZATION', label: STEP_LABELS.DIARIZATION },
  { key: 'VOICEPRINT_MATCHING', label: STEP_LABELS.VOICEPRINT_MATCHING },
  { key: 'PREPARING_REVIEW', label: STEP_LABELS.PREPARING_REVIEW },
  { key: 'GENERATING_MINUTES', label: STEP_LABELS.GENERATING_MINUTES },
]

export function stateLabel(state: string | null | undefined): string {
  if (!state) {
    return '—'
  }
  return STATE_LABELS[state] ?? state
}

// 状态点的色系：进行中 / 停点 / 完成 / 出错
export function stateTone(state: string): 'active' | 'attention' | 'done' | 'error' | 'muted' {
  switch (state) {
    case 'AWAITING_SPEAKER_REVIEW':
    case 'PARTIAL_READY':
      return 'attention'
    case 'READY':
      return 'done'
    case 'FAILED':
      return 'error'
    case 'CANCELED':
    case 'DRAFT':
      return 'muted'
    default:
      return 'active'
  }
}
