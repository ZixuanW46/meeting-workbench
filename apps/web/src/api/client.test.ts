import { HttpResponse, http } from 'msw'
import { server } from '../test/server'
import {
  ApiError,
  createMeeting,
  formatApiError,
  listMeetings,
  submitDecisions,
} from './client'

const MEETING = {
  id: 'm1',
  title: '周会',
  state: 'DRAFT',
  expected_speakers: null,
  hotwords: [],
  created_at: '2026-08-26T08:00:00Z',
}

describe('api client', () => {
  it('listMeetings 解析 items', async () => {
    server.use(
      http.get('/api/meetings', () => HttpResponse.json({ items: [MEETING] })),
    )

    const meetings = await listMeetings()

    expect(meetings).toHaveLength(1)
    expect(meetings[0].title).toBe('周会')
  })

  it('createMeeting 发送标题、人数与热词', async () => {
    let body: unknown = null
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(MEETING, { status: 201 })
      }),
    )

    await createMeeting({ title: '周会', expected_speakers: null, hotwords: ['声纹'] })

    expect(body).toEqual({ title: '周会', expected_speakers: null, hotwords: ['声纹'] })
  })

  it('409 缺卡错误带 missing_cluster_ids 并渲染成缺卡提示', async () => {
    server.use(
      http.post('/api/meetings/m1/review/decisions', () =>
        HttpResponse.json(
          {
            detail: {
              message: "以下说话人卡还没有决定: ['S2']",
              missing_cluster_ids: ['S2', 'S3'],
            },
          },
          { status: 409 },
        ),
      ),
    )

    const error = await submitDecisions('m1', [
      { cluster_id: 'S1', kind: 'CONFIRM' },
    ]).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    const apiError = error as ApiError
    expect(apiError.status).toBe(409)
    expect(apiError.missingClusterIds).toEqual(['S2', 'S3'])
    expect(formatApiError(apiError)).toBe('还有说话人卡未提交决定：S2、S3')
  })

  it('普通 detail 字符串错误原样展示', async () => {
    server.use(
      http.get('/api/meetings/m404', () =>
        HttpResponse.json({ detail: '会议不存在' }, { status: 404 }),
      ),
    )

    const error = await listMeetingsFrom('/api/meetings/m404')

    expect(formatApiError(error)).toBe('会议不存在')
  })
})

async function listMeetingsFrom(url: string): Promise<unknown> {
  const { apiFetch } = await import('./client')
  return apiFetch(url).catch((e: unknown) => e)
}
