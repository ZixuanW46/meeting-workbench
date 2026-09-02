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
      suggested_tier: 'high',
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
      suggested_tier: null,
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

const TAIL_CARDS = {
  cards: [
    REVIEW.cards[0],
    REVIEW.cards[1],
    {
      cluster_id: 'S3',
      total_seconds: 2.0,
      suggested_person_id: null,
      suggested_display_name: null,
      sample_clips: [{ start_seconds: 11, end_seconds: 12, text: '' }],
      text: '',
    },
    {
      cluster_id: 'S4',
      total_seconds: 1.2,
      suggested_person_id: null,
      suggested_display_name: null,
      suggested_tier: null,
      sample_clips: [{ start_seconds: 13, end_seconds: 14, text: '' }],
      text: '',
    },
  ],
  people: REVIEW.people,
}

const NO_ANCHOR = {
  cards: [REVIEW.cards[1], TAIL_CARDS.cards[2], TAIL_CARDS.cards[3]],
  people: [],
}

describe('说话人确认页固定提交栏', () => {
  it('提交栏常驻并显示「已决定 x / y」，随选择更新', async () => {
    mockReview()
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    await findCard('S2')
    const footer = screen.getByTestId('review-footer')
    expect(footer).toHaveClass('review-footer-sticky')
    // S1 的「较高」建议已预选
    expect(within(footer).getByText('已决定 1 / 2')).toBeInTheDocument()

    fireEvent.click(
      within(await findCard('S2')).getByLabelText('保持匿名（标为说话人 2）'),
    )
    expect(within(footer).getByText('已决定 2 / 2')).toBeInTheDocument()
    expect(within(footer).getByRole('button', { name: '提交确认' })).toBeEnabled()
  })

  it('本场没有任何已确认者时，「并入最近的已确认参会人」不可选，批量按钮也禁用', async () => {
    server.use(
      http.get('/api/meetings/m1/review', () => HttpResponse.json(NO_ANCHOR)),
    )
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    const card = await findCard('S2')
    const nearest = within(card).getByLabelText('并入最近的已确认参会人')
    expect(nearest).toBeDisabled()
    expect(
      screen.getByRole('button', { name: '并入已确认参会人（按声纹就近）' }),
    ).toBeDisabled()

    // 给 S2 起个名字后，其他卡的就近归属就有锚点了
    fireEvent.click(within(card).getByLabelText('新建人'))
    fireEvent.change(within(card).getByPlaceholderText('输入显示名'), {
      target: { value: '王芳' },
    })
    expect(
      within(await findCard('S3')).getByLabelText('并入最近的已确认参会人'),
    ).toBeEnabled()
    // 只剩 2 张未决定，批量栏按既有规则收起
    expect(screen.queryByText(/张未决定：/)).not.toBeInTheDocument()
  })
})

describe('说话人确认卡', () => {
  it('尾簇批量栏：一键就近归属，可再逐卡覆盖，提交带 NEAREST_CONFIRMED', async () => {
    server.use(
      http.get('/api/meetings/m1/review', () => HttpResponse.json(TAIL_CARDS)),
    )
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

    await findCard('S4')
    // S1 的「较高」建议已默认选中确认，未决定的只有 3 张尾卡
    expect(screen.getByText('其余 3 张未决定：')).toBeInTheDocument()

    fireEvent.click(
      screen.getByRole('button', { name: '并入已确认参会人（按声纹就近）' }),
    )
    // 批量后逐卡覆盖：S1 改为确认建议身份
    fireEvent.click(within(await findCard('S1')).getByLabelText('确认建议身份'))
    // 选中就近的卡头出现预览 chip；批量栏因无未决定卡而消失
    expect(
      within(await findCard('S2')).getByText('将按声纹并入最近的已确认参会人'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/张未决定：/)).not.toBeInTheDocument()

    const submit = screen.getByRole('button', { name: '提交确认' })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled())
    expect(body).toEqual({
      decisions: [
        { cluster_id: 'S1', kind: 'CONFIRM' },
        { cluster_id: 'S2', kind: 'NEAREST_CONFIRMED' },
        { cluster_id: 'S3', kind: 'NEAREST_CONFIRMED' },
        { cluster_id: 'S4', kind: 'NEAREST_CONFIRMED' },
      ],
    })
  })

  it('文案：预选说明诚实、批量提示不再提「（就近归属）」标注', async () => {
    server.use(
      http.get('/api/meetings/m1/review', () => HttpResponse.json(TAIL_CARDS)),
    )
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    await findCard('S4')
    expect(
      screen.getByText(
        /较高匹配已预选，过目后提交即可；系统只提供建议，「暂不确定」也合法/,
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText('就近归属按声纹并入已确认的人，不进声纹库；转写与纪要不再另标。'),
    ).toBeInTheDocument()
    // 标签已移除，任何文案不得再承诺「（就近归属）」标注
    expect(screen.queryByText(/（就近归属）/)).not.toBeInTheDocument()
  })

  it('尾簇批量栏：全部保持匿名触发未确认提示', async () => {
    server.use(
      http.get('/api/meetings/m1/review', () => HttpResponse.json(TAIL_CARDS)),
    )
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    await findCard('S4')
    fireEvent.click(screen.getByRole('button', { name: '全部保持匿名' }))

    expect(screen.getByText(/含未确认说话人/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '提交确认' })).toBeEnabled()
  })

  it('卡片按显示顺序编号为说话人 1、2……而非簇代号', async () => {
    mockReview()
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    expect(within(await findCard('S1')).getByText('说话人 1')).toBeInTheDocument()
    expect(within(await findCard('S2')).getByText('说话人 2')).toBeInTheDocument()
    expect(screen.queryByText('说话人 S1')).not.toBeInTheDocument()
  })

  it('「较高」建议默认选中确认建议身份，卡片带降噪样式', async () => {
    mockReview()
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    const cardS1 = await findCard('S1')
    expect(within(cardS1).getByLabelText('确认建议身份')).toBeChecked()
    expect(cardS1.className).toContain('suggested-high')

    const cardS2 = await findCard('S2')
    expect(cardS2.className).not.toContain('suggested-high')
    // 无建议的卡不预选任何决定
    const radios = within(cardS2).getAllByRole('radio')
    expect(radios.some((r) => (r as HTMLInputElement).checked)).toBe(false)
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

  it('建议档位「较高」随建议人名定性展示', async () => {
    // 红线：只有「较高 / 需判断」两档，绝不显示数值置信度。
    mockReview()
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    expect(
      within(await findCard('S1')).getByText('建议：王芳 · 较高'),
    ).toBeInTheDocument()
  })

  it('相似度居中或缺档位信息时显示「需判断」', async () => {
    server.use(
      http.get('/api/meetings/m1/review', () =>
        HttpResponse.json({
          ...REVIEW,
          cards: [
            { ...REVIEW.cards[0], suggested_tier: 'uncertain' },
            REVIEW.cards[1],
          ],
        }),
      ),
    )
    render(<SpeakerReview meetingId="m1" onSubmitted={() => {}} />)

    expect(
      within(await findCard('S1')).getByText('建议：王芳 · 需判断'),
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
