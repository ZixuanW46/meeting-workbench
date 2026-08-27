import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server } from '../test/server'
import { SpeakerReview } from './SpeakerReview'

vi.mock('wavesurfer.js', () => ({
  default: {
    create: vi.fn(() => ({
      on: vi.fn(),
      un: vi.fn(),
      destroy: vi.fn(),
      play: vi.fn(),
      pause: vi.fn(),
      setTime: vi.fn(),
      getDuration: vi.fn(() => 10),
    })),
  },
}))

const REVIEW = {
  cards: [
    {
      cluster_id: 'S1',
      total_seconds: 450.1,
      suggested_person_id: 'fake-person-1',
      suggested_display_name: '王芳',
      sample_clips: [
        { start_seconds: 0, end_seconds: 2.5, text: '大家好，开始周会。' },
        { start_seconds: 6, end_seconds: 8, text: '' },
      ],
      text: '大家好，开始周会。',
    },
    {
      cluster_id: 'S2',
      total_seconds: 3.5,
      suggested_person_id: null,
      suggested_display_name: null,
      sample_clips: [
        { start_seconds: 3, end_seconds: 5, text: '我补充一下进度。' },
        { start_seconds: 9, end_seconds: 10, text: '' },
      ],
      text: '我补充一下进度。',
    },
  ],
  people: [{ id: 'fake-person-1', display_name: '王芳' }],
}

function mockReview() {
  server.use(
    http.get('/api/meetings/m1/review', () => HttpResponse.json(REVIEW)),
  )
}

async function findCard(clusterId: string) {
  return await screen.findByTestId(`speaker-card-${clusterId}`)
}

describe('说话人确认卡', () => {
  it('卡片数多于预计人数时提示用「合并」归并', async () => {
    mockReview()
    render(
      <SpeakerReview meetingId="m1" expectedSpeakers={1} onSubmitted={() => {}} />,
    )

    await findCard('S1')
    expect(
      screen.getByText(/切分聚出 2 位说话人，多于预计的 1/),
    ).toBeInTheDocument()
    expect(screen.getByText(/「与其他说话人合并」归并/)).toBeInTheDocument()
  })

  it('未填预计人数或卡片不超时不出现过分聚类提示', async () => {
    mockReview()
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    await findCard('S1')
    expect(screen.queryByText(/多于预计的/)).not.toBeInTheDocument()
  })

  it('每卡必须选择一个决定后「提交」才可点', async () => {
    mockReview()
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    const cardS1 = await findCard('S1')
    const cardS2 = await findCard('S2')
    const submit = screen.getByRole('button', { name: '提交确认' })
    expect(submit).toBeDisabled()

    fireEvent.click(within(cardS1).getByLabelText('确认建议身份'))
    expect(submit).toBeDisabled()

    fireEvent.click(within(cardS2).getByLabelText('保持匿名（标为说话人 2）'))
    expect(submit).toBeEnabled()
  })

  it('含未知决定时出现「含未确认说话人」提示，提交发送决定', async () => {
    mockReview()
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('/api/meetings/m1/review/decisions', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          state: 'GENERATING_MINUTES',
          has_unconfirmed_speakers: true,
        })
      }),
    )
    const onSubmitted = vi.fn()
    render(<SpeakerReview meetingId="m1" onSubmitted={onSubmitted} />)

    fireEvent.click(within(await findCard('S1')).getByLabelText('确认建议身份'))
    expect(screen.queryByText(/含未确认说话人/)).not.toBeInTheDocument()

    fireEvent.click(within(await findCard('S2')).getByLabelText('保持匿名（标为说话人 2）'))
    expect(screen.getByText(/含未确认说话人/)).toBeInTheDocument()
    // 选中保持匿名后，卡头预览最终标注
    expect(within(await findCard('S2')).getByText('将标为：说话人 2')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '提交确认' }))

    await waitFor(() => expect(onSubmitted).toHaveBeenCalled())
    expect(body).toEqual({
      decisions: [
        { cluster_id: 'S1', kind: 'CONFIRM' },
        { cluster_id: 'S2', kind: 'UNDECIDED_UNKNOWN' },
      ],
    })
  })

  it('新建人必须填显示名才能提交', async () => {
    mockReview()
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    fireEvent.click(within(await findCard('S1')).getByLabelText('确认建议身份'))
    const cardS2 = await findCard('S2')
    fireEvent.click(within(cardS2).getByLabelText('新建人'))

    const submit = screen.getByRole('button', { name: '提交确认' })
    expect(submit).toBeDisabled()

    fireEvent.change(within(cardS2).getByPlaceholderText('输入显示名'), {
      target: { value: '张三' },
    })
    expect(submit).toBeEnabled()
  })

  it('卡头显示该簇累计发言时长', async () => {
    // 几十张卡时，人工靠累计时长判断哪些卡值得细听。
    mockReview()
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    expect(
      within(await findCard('S1')).getByText('累计发言 7:30'),
    ).toBeInTheDocument()
    expect(
      within(await findCard('S2')).getByText('累计发言 0:03'),
    ).toBeInTheDocument()
  })

  it('试听子卡展示该片段的逐段转写与建议人名', async () => {
    mockReview()
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    const cardS1 = await findCard('S1')
    expect(within(cardS1).getByText('大家好，开始周会。')).toBeInTheDocument()
    expect(within(cardS1).getByText(/建议：王芳/)).toBeInTheDocument()
    // 每个片段有独立试听按钮（带时间范围的可访问名）
    expect(
      within(cardS1).getByRole('button', { name: /试听 0:00\.0–0:02\.5/ }),
    ).toBeInTheDocument()
  })

  it('从声纹库选择需选定人员，提交带 person_id', async () => {
    mockReview()
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('/api/meetings/m1/review/decisions', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          state: 'GENERATING_MINUTES',
          has_unconfirmed_speakers: false,
        })
      }),
    )
    const onSubmitted = vi.fn()
    render(<SpeakerReview meetingId="m1" onSubmitted={onSubmitted} />)

    fireEvent.click(within(await findCard('S1')).getByLabelText('确认建议身份'))
    const cardS2 = await findCard('S2')
    fireEvent.click(within(cardS2).getByLabelText('从声纹库选择'))

    const submit = screen.getByRole('button', { name: '提交确认' })
    expect(submit).toBeDisabled()

    fireEvent.change(within(cardS2).getByLabelText('选择已有人'), {
      target: { value: 'fake-person-1' },
    })
    expect(submit).toBeEnabled()

    fireEvent.click(submit)
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled())
    expect(body).toEqual({
      decisions: [
        { cluster_id: 'S1', kind: 'CONFIRM' },
        { cluster_id: 'S2', kind: 'LINK_EXISTING', person_id: 'fake-person-1' },
      ],
    })
  })

  it('后端 409 缺卡渲染成缺卡提示', async () => {
    mockReview()
    server.use(
      http.post('/api/meetings/m1/review/decisions', () =>
        HttpResponse.json(
          {
            detail: {
              message: "以下说话人卡还没有决定: ['S2']",
              missing_cluster_ids: ['S2'],
            },
          },
          { status: 409 },
        ),
      ),
    )
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    fireEvent.click(within(await findCard('S1')).getByLabelText('确认建议身份'))
    fireEvent.click(within(await findCard('S2')).getByLabelText('保持匿名（标为说话人 2）'))
    fireEvent.click(screen.getByRole('button', { name: '提交确认' }))

    expect(
      await screen.findByText('还有说话人卡未提交决定：S2'),
    ).toBeInTheDocument()
  })
})
