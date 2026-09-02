// 统一的 fetch 封装：JSON 解析、错误对象化、缺卡 409 识别。
// 业务规则（每卡必须有决定等）以后端为准，这里只做传输与错误翻译。

export interface Meeting {
  id: string
  title: string
  state: string
  expected_speakers: number | null
  hotwords: string[]
  created_at: string
  /** 生效的会议日期（YYYY-MM-DD）：纪要标题与相对日期换算的锚点 */
  meeting_date: string
  /** user=用户填写 / filename=按音频文件名推断 / created=按创建日 */
  meeting_date_source: 'user' | 'filename' | 'created'
  /** 已确认身份的参会人显示名，按累计发言时长降序；未完成确认时为空 */
  speakers: string[]
  /** 确认后仍未落名的说话人簇数 */
  unknown_speaker_count: number
  /** FAILED / PARTIAL_READY 的失败原因，给人看的一句话 */
  processing_error: string | null
}

export interface MeetingCreateInput {
  /** 选填：留空则后端先占位，上传后取文件名、纪要后自动命名 */
  title?: string
  hotwords: string[]
  /** 会议发生日（YYYY-MM-DD）；不传则后端按文件名或创建日推断 */
  meeting_date?: string
}

export interface MeetingUpdateInput {
  title?: string
  meeting_date?: string
}

export interface ReviewSample {
  start_seconds: number
  end_seconds: number
  /** 该时间窗内、同簇的逐段转写摘录；无覆盖时为空串 */
  text: string
}

export interface ReviewCard {
  cluster_id: string
  /** 该簇累计发言秒数（切分产物口径），卡片按它降序返回 */
  total_seconds: number
  suggested_person_id: string | null
  /** 建议身份显示名：定性表达，后端绝不附带数值置信度 */
  suggested_display_name: string | null
  /** 建议档位仅两档：high=「较高」/ uncertain=「需判断」；无建议时为 null */
  suggested_tier: 'high' | 'uncertain' | null
  sample_clips: ReviewSample[]
  text: string
}

export interface ReviewPerson {
  id: string
  display_name: string
}

export type DecisionKind =
  | 'CONFIRM'
  | 'REASSIGN'
  | 'KEEP_UNKNOWN'
  | 'NEW_PERSON'
  | 'LINK_EXISTING'
  | 'MERGE_WITH_CLUSTER'
  | 'UNDECIDED_UNKNOWN'
  | 'NEAREST_CONFIRMED'

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
  /** 步骤内进度，如清洗「3/12」 */
  detail?: string | null
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
  /** 入库时间（ISO），0010 之前的存量模板为 null */
  created_at: string | null
  /** 模板来源会议标题；绝不是文件路径 */
  source_meeting_title: string | null
  /** 该模板试听窗对应的转写摘录 */
  snippet_text: string
  /** 是否有试听切片可播放 */
  has_clip: boolean
}

export interface VoiceprintPerson {
  id: string
  display_name: string
}

/** 声纹库全貌：people 是全部参会人（含暂无模板者），与确认页人员口径一致 */
export interface VoiceprintLibrary {
  items: Voiceprint[]
  people: VoiceprintPerson[]
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

export function updateMeeting(
  meetingId: string,
  patch: MeetingUpdateInput,
): Promise<Meeting> {
  return apiFetch<Meeting>(`/api/meetings/${meetingId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

export function updateMeetingTitle(meetingId: string, title: string): Promise<Meeting> {
  return updateMeeting(meetingId, { title })
}

/** 本机时区的今天，YYYY-MM-DD；日期输入框默认值用。 */
export function localToday(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

/** 取消处理：排队/转写中 → CANCELED；生成纪要中 → PARTIAL_READY（转写与确认保留） */
export function cancelMeeting(meetingId: string): Promise<Meeting> {
  return apiFetch<Meeting>(`/api/meetings/${meetingId}/cancel`, { method: 'POST' })
}

/** 显式重转写：清掉转写、确认与纪要，音频不动，回到排队 */
export function retranscribeMeeting(meetingId: string): Promise<Meeting> {
  return apiFetch<Meeting>(`/api/meetings/${meetingId}/retranscribe`, { method: 'POST' })
}

export function deleteMeeting(meetingId: string): Promise<void> {
  return apiFetch<void>(`/api/meetings/${meetingId}`, { method: 'DELETE' })
}

export function uploadAudio(
  meetingId: string,
  file: File,
): Promise<{ size: number; sha256: string }> {
  const form = new FormData()
  form.append('file', file)
  return apiFetch(`/api/meetings/${meetingId}/upload`, { method: 'POST', body: form })
}

export function getReview(
  meetingId: string,
): Promise<{ cards: ReviewCard[]; people: ReviewPerson[] }> {
  return apiFetch(`/api/meetings/${meetingId}/review`)
}

export function submitDecisions(
  meetingId: string,
  decisions: SpeakerDecisionInput[],
): Promise<ReviewSubmitResult> {
  return postJson(`/api/meetings/${meetingId}/review/decisions`, { decisions })
}

export function reopenReview(meetingId: string): Promise<{ state: string }> {
  return apiFetch(`/api/meetings/${meetingId}/review/reopen`, { method: 'POST' })
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

/** 转写版本：cleaned=LLM 清洗版（去语气词、修标点，不改语义），raw=ASR 原文 */
export type TranscriptVariant = 'cleaned' | 'raw'

export interface TranscriptBlock {
  start_seconds: number
  end_seconds: number
  /** 公开说话人标签：确认后的名字或「说话人 N」 */
  label: string
  /** ASR 原文 */
  text: string
  /** LLM 清洗文本；该块清洗失败或哈希对不上时为 null，展示时回退原文 */
  cleaned_text: string | null
}

export interface TranscriptResult {
  blocks: TranscriptBlock[]
  /** 至少有一块有清洗文本；工具栏据此决定是否出切换按钮 */
  cleaned_available: boolean
}

export function getTranscript(meetingId: string): Promise<TranscriptResult> {
  return apiFetch<TranscriptResult>(`/api/meetings/${meetingId}/transcript`)
}

export function getDoctor(): Promise<DoctorReport> {
  return apiFetch<DoctorReport>('/api/doctor')
}

export function listVoiceprints(): Promise<VoiceprintLibrary> {
  return apiFetch<VoiceprintLibrary>('/api/voiceprints')
}

export function deleteVoiceprint(voiceprintId: string): Promise<void> {
  return apiFetch<void>(`/api/voiceprints/${voiceprintId}`, { method: 'DELETE' })
}

export function voiceprintAudioUrl(voiceprintId: string): string {
  return `/api/voiceprints/${voiceprintId}/audio`
}

export interface Hotword {
  id: string
  word: string
  // 注解只喂给纪要 LLM 当术语参考，转写热词仍只用词本身。
  note: string | null
}

export async function listHotwords(): Promise<Hotword[]> {
  const data = await apiFetch<{ items: Hotword[] }>('/api/hotwords')
  return data.items
}

export function createHotword(word: string, note?: string): Promise<Hotword> {
  return postJson<Hotword>(
    '/api/hotwords',
    note === undefined ? { word } : { word, note },
  )
}

export function updateHotwordNote(
  hotwordId: string,
  note: string | null,
): Promise<Hotword> {
  return apiFetch<Hotword>(`/api/hotwords/${hotwordId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note }),
  })
}

export function deleteHotword(hotwordId: string): Promise<void> {
  return apiFetch<void>(`/api/hotwords/${hotwordId}`, { method: 'DELETE' })
}

/** 整场音频的波形峰值（后端算一次并缓存）：≤2000 桶、0～1，附时长秒数 */
export interface AudioPeaks {
  duration: number
  peaks: number[]
}

export function getPeaks(meetingId: string): Promise<AudioPeaks> {
  return apiFetch<AudioPeaks>(`/api/meetings/${meetingId}/peaks`)
}

export function audioUrl(meetingId: string): string {
  return `/api/meetings/${meetingId}/audio`
}

export function eventsUrl(meetingId: string): string {
  return `/api/meetings/${meetingId}/events`
}

export const exportUrls = {
  transcriptMd: (meetingId: string, variant: TranscriptVariant = 'raw') =>
    `/api/meetings/${meetingId}/export/transcript.md?variant=${variant}`,
  minutesMd: (meetingId: string) => `/api/meetings/${meetingId}/export/minutes.md`,
  minutesDocx: (meetingId: string) => `/api/meetings/${meetingId}/export/minutes.docx`,
}
