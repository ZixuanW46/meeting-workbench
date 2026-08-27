// 统一的 fetch 封装：JSON 解析、错误对象化、缺卡 409 识别。
// 业务规则（每卡必须有决定等）以后端为准，这里只做传输与错误翻译。

export interface Meeting {
  id: string
  title: string
  state: string
  expected_speakers: number | null
  hotwords: string[]
  created_at: string
}

export interface MeetingCreateInput {
  title: string
  expected_speakers: number | null
  hotwords: string[]
}

export interface ReviewSample {
  start_seconds: number
  end_seconds: number
}

export interface ReviewCard {
  cluster_id: string
  suggested_person_id: string | null
  sample_clips: ReviewSample[]
  text: string
}

export type DecisionKind =
  | 'CONFIRM'
  | 'REASSIGN'
  | 'KEEP_UNKNOWN'
  | 'NEW_PERSON'
  | 'LINK_EXISTING'
  | 'MERGE_WITH_CLUSTER'
  | 'UNDECIDED_UNKNOWN'

export interface SpeakerDecisionInput {
  cluster_id: string
  kind: DecisionKind
  person_id?: string
  merge_into_cluster_id?: string
  display_name?: string
}

export interface ReviewSubmitResult {
  state: string
  has_unconfirmed_speakers: boolean
}

export interface ProgressSnapshot {
  state: string
  processing_step: string | null
  seq: number
}

export interface MinutesResult {
  markdown: string
  note: string
}

// GET /api/doctor 的响应，字段与后端 DoctorResponse 一一对应
export interface DoctorModels {
  asr: boolean
  segmentation: boolean
  embedding: boolean
}

// 只报告 CLI 是否在 PATH：登录检查需要交互终端，服务端在 launchd 下探测必然
// 误报；登录问题由生成环节暴露（PARTIAL_READY + 重试）。
export interface DoctorCli {
  claude_available: boolean
  codex_available: boolean
}

export interface DoctorReport {
  ffmpeg: boolean
  models: DoctorModels
  cli: DoctorCli
  disk_gb_free: number
  transcription_ready: boolean
  minutes_ready: boolean
}

export interface Voiceprint {
  id: string
  person_id: string
  display_name: string
}

export class ApiError extends Error {
  status: number
  detail: unknown
  missingClusterIds: string[] | null

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `请求失败（${status}）`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.missingClusterIds = extractMissingClusterIds(detail)
  }
}

function extractMissingClusterIds(detail: unknown): string[] | null {
  if (
    detail !== null &&
    typeof detail === 'object' &&
    'missing_cluster_ids' in detail &&
    Array.isArray((detail as { missing_cluster_ids: unknown }).missing_cluster_ids)
  ) {
    return (detail as { missing_cluster_ids: unknown[] }).missing_cluster_ids.map(String)
  }
  return null
}

async function readErrorDetail(response: Response): Promise<unknown> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    return body && typeof body === 'object' && 'detail' in body ? body.detail : body
  } catch {
    return null
  }
}

export async function apiFetch<T = unknown>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new ApiError(response.status, await readErrorDetail(response))
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export async function apiFetchText(url: string): Promise<string> {
  const response = await fetch(url)
  if (!response.ok) {
    throw new ApiError(response.status, await readErrorDetail(response))
  }
  return await response.text()
}

function postJson<T>(url: string, body: unknown): Promise<T> {
  return apiFetch<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function formatApiError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.missingClusterIds && error.missingClusterIds.length > 0) {
      return `还有说话人卡未提交决定：${error.missingClusterIds.join('、')}`
    }
    if (typeof error.detail === 'string') {
      return error.detail
    }
    if (
      error.detail !== null &&
      typeof error.detail === 'object' &&
      'message' in error.detail &&
      typeof (error.detail as { message: unknown }).message === 'string'
    ) {
      return (error.detail as { message: string }).message
    }
    return `请求失败（${error.status}）`
  }
  if (error instanceof Error && error.message) {
    return `网络错误：${error.message}`
  }
  return '请求失败'
}

export async function listMeetings(): Promise<Meeting[]> {
  const data = await apiFetch<{ items: Meeting[] }>('/api/meetings')
  return data.items
}

export function getMeeting(meetingId: string): Promise<Meeting> {
  return apiFetch<Meeting>(`/api/meetings/${meetingId}`)
}

export function createMeeting(input: MeetingCreateInput): Promise<Meeting> {
  return postJson<Meeting>('/api/meetings', input)
}

export function uploadAudio(
  meetingId: string,
  file: File,
): Promise<{ size: number; sha256: string }> {
  const form = new FormData()
  form.append('file', file)
  return apiFetch(`/api/meetings/${meetingId}/upload`, { method: 'POST', body: form })
}

export function getReview(meetingId: string): Promise<{ cards: ReviewCard[] }> {
  return apiFetch(`/api/meetings/${meetingId}/review`)
}

export function submitDecisions(
  meetingId: string,
  decisions: SpeakerDecisionInput[],
): Promise<ReviewSubmitResult> {
  return postJson(`/api/meetings/${meetingId}/review/decisions`, { decisions })
}

export function getProgress(meetingId: string): Promise<ProgressSnapshot> {
  return apiFetch(`/api/meetings/${meetingId}/progress`)
}

export function getMinutes(meetingId: string): Promise<MinutesResult> {
  return apiFetch(`/api/meetings/${meetingId}/minutes`)
}

export function retryMinutes(meetingId: string): Promise<{ state: string }> {
  return apiFetch(`/api/meetings/${meetingId}/minutes/retry`, { method: 'POST' })
}

export function getTranscriptMarkdown(meetingId: string): Promise<string> {
  return apiFetchText(`/api/meetings/${meetingId}/export/transcript.md`)
}

export function getDoctor(): Promise<DoctorReport> {
  return apiFetch<DoctorReport>('/api/doctor')
}

export async function listVoiceprints(): Promise<Voiceprint[]> {
  const data = await apiFetch<{ items: Voiceprint[] }>('/api/voiceprints')
  return data.items
}

export function deleteVoiceprint(voiceprintId: string): Promise<void> {
  return apiFetch<void>(`/api/voiceprints/${voiceprintId}`, { method: 'DELETE' })
}

export function audioUrl(meetingId: string): string {
  return `/api/meetings/${meetingId}/audio`
}

export function eventsUrl(meetingId: string): string {
  return `/api/meetings/${meetingId}/events`
}

export const exportUrls = {
  transcriptMd: (meetingId: string) => `/api/meetings/${meetingId}/export/transcript.md`,
  minutesMd: (meetingId: string) => `/api/meetings/${meetingId}/export/minutes.md`,
  minutesDocx: (meetingId: string) => `/api/meetings/${meetingId}/export/minutes.docx`,
}
