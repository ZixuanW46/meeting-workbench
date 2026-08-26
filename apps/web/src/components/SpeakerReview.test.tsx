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
      suggested_person_id: 'fake-person-1',
      sample_clips: [
        { start_seconds: 0, end_seconds: 2.5 },
        { start_seconds: 6, end_seconds: 8 },
      ],
      text: '大家好，开始周会。',
    },
    {
      cluster_id: 'S2',
      suggested_person_id: null,
      sample_clips: [
        { start_seconds: 3, end_seconds: 5 },
        { start_seconds: 9, end_seconds: 10 },
      ],
      text: '我补充一下进度。',
    },
  ],
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
  it('每卡必须选择一个决定后「提交」才可点', async () => {
    mockReview()
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    const cardS1 = await findCard('S1')
    const cardS2 = await findCard('S2')
    const submit = screen.getByRole('button', { name: '提交确认' })
    expect(submit).toBeDisabled()

    fireEvent.click(within(cardS1).getByLabelText('确认建议身份'))
    expect(submit).toBeDisabled()

    fireEvent.click(within(cardS2).getByLabelText('暂不确定'))
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

    fireEvent.click(within(await findCard('S2')).getByLabelText('暂不确定'))
    expect(screen.getByText(/含未确认说话人/)).toBeInTheDocument()

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
    fireEvent.click(within(await findCard('S2')).getByLabelText('暂不确定'))
    fireEvent.click(screen.getByRole('button', { name: '提交确认' }))

    expect(
      await screen.findByText('还有说话人卡未提交决定：S2'),
    ).toBeInTheDocument()
  })
})
