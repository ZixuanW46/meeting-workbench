import { fireEvent, render, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { afterEach } from 'vitest'
import type { TranscriptVariant } from '../api/client'
import { server } from '../test/server'
import { resetPlaybackForTests } from './clipPlayback'
import { TranscriptView } from './TranscriptView'

afterEach(() => {
  resetPlaybackForTests()
})

// 后端给块级 JSON：起止秒、公开标签、原文、清洗文本（没有就 null）。
const RAW_BLOCKS = [
  {
    start_seconds: 0,
    end_seconds: 58,
    label: '已知用户 1',
    text: '嗯，大家好，今天今天对齐三件事。首先是上线时间。',
  },
  {
    start_seconds: 58,
    end_seconds: 100,
    label: '说话人S2（未确认）',
    text: '呃，我这边周五可以发布。',
  },
  { start_seconds: 4090, end_seconds: 4125, label: '李四（就近归属）', text: '收到。' },
]

const CLEANED_TEXTS = [
  '大家好，今天对齐三件事。首先是上线时间。',
  '我这边周五可以发布。',
  '收到。',
]

function mockTranscript(withCleaned: boolean, blocks = RAW_BLOCKS) {
  server.use(
    http.get('/api/meetings/m1/transcript', () =>
      HttpResponse.json({
        blocks: blocks.map((block, index) => ({
          ...block,
          cleaned_text: withCleaned ? CLEANED_TEXTS[index] : null,
        })),
        cleaned_available: withCleaned,
      }),
    ),
  )
}

function renderView(
  variant: TranscriptVariant,
  onCleanedAvailable?: (available: boolean) => void,
) {
  return render(
    <TranscriptView
      meetingId="m1"
      variant={variant}
      onCleanedAvailable={onCleanedAvailable}
    />,
  )
}

describe('转写视图', () => {
  it('把块渲染成「时间 / 说话人 / 文本」行，秒数格式化成 mm:ss 或 h:mm:ss', async () => {
    mockTranscript(false)

    renderView('cleaned')

    expect(await screen.findByText('已知用户 1')).toBeInTheDocument()
    expect(screen.getByText('00:00 – 00:58')).toBeInTheDocument()
    expect(
      screen.getByText('嗯，大家好，今天今天对齐三件事。首先是上线时间。'),
    ).toBeInTheDocument()
    expect(screen.getByText('说话人S2（未确认）')).toBeInTheDocument()
    expect(screen.getByText('00:58 – 01:40')).toBeInTheDocument()
    // 超一小时的 h:mm:ss 时间戳同样可解析。
    expect(screen.getByText('李四（就近归属）')).toBeInTheDocument()
    expect(screen.getByText('1:08:10 – 1:08:45')).toBeInTheDocument()
  })

  it('有清洗版且口径为 cleaned 时展示清洗文本，并上报清洗版可用', async () => {
    mockTranscript(true)
    const reported: boolean[] = []

    renderView('cleaned', (available) => reported.push(available))

    expect(
      await screen.findByText('大家好，今天对齐三件事。首先是上线时间。'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('嗯，大家好，今天今天对齐三件事。首先是上线时间。'),
    ).not.toBeInTheDocument()
    expect(reported).toEqual([true])
  })

  it('口径为 raw 时展示 ASR 直出文本', async () => {
    mockTranscript(true)

    renderView('raw')

    expect(
      await screen.findByText('嗯，大家好，今天今天对齐三件事。首先是上线时间。'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('大家好，今天对齐三件事。首先是上线时间。'),
    ).not.toBeInTheDocument()
  })

  it('没有清洗版时展示原文并上报不可用', async () => {
    mockTranscript(false)
    const reported: boolean[] = []

    renderView('cleaned', (available) => reported.push(available))

    expect(await screen.findByText('已知用户 1')).toBeInTheDocument()
    expect(reported).toEqual([false])
  })

  it('一个块都没有时给空态说明', async () => {
    mockTranscript(false, [])

    renderView('cleaned')

    expect(await screen.findByText('本场会议没有逐字稿')).toBeInTheDocument()
  })

  it('某块清洗失败回退原文时，清洗口径下该行显示原文', async () => {
    server.use(
      http.get('/api/meetings/m1/transcript', () =>
        HttpResponse.json({
          blocks: [
            { ...RAW_BLOCKS[0], cleaned_text: CLEANED_TEXTS[0] },
            { ...RAW_BLOCKS[1], cleaned_text: null },
          ],
          cleaned_available: true,
        }),
      ),
    )

    renderView('cleaned')

    expect(
      await screen.findByText('大家好，今天对齐三件事。首先是上线时间。'),
    ).toBeInTheDocument()
    expect(screen.getByText('呃，我这边周五可以发布。')).toBeInTheDocument()
  })

  it('点行首播放键 seek 到块起点，同刻只有一行在播', async () => {
    mockTranscript(false)

    renderView('raw')

    const first = await screen.findByRole('button', {
      name: '播放 00:00 – 00:58 原声',
    })
    const audio = screen.getByTestId('transcript-audio') as HTMLAudioElement

    fireEvent.click(first)
    expect(
      screen.getByRole('button', { name: '暂停 00:00 – 00:58 原声' }),
    ).toBeInTheDocument()
    // 元数据就绪后从块起点开播（jsdom readyState 恒 0，手动补事件）。
    fireEvent(audio, new Event('loadedmetadata'))
    expect(audio.currentTime).toBe(0)

    // 换一行开播：前一行回到「播放」态，h:mm:ss 起点同样可反解。
    fireEvent.click(
      screen.getByRole('button', { name: '播放 1:08:10 – 1:08:45 原声' }),
    )
    expect(
      screen.getByRole('button', { name: '播放 00:00 – 00:58 原声' }),
    ).toBeInTheDocument()
    fireEvent(audio, new Event('loadedmetadata'))
    expect(audio.currentTime).toBe(4090)
  })

  it('元数据加载完成前已暂停的行不会开播', async () => {
    mockTranscript(false)

    renderView('raw')

    // 点播后立刻暂停（jsdom readyState 恒 0，正处于等元数据窗口）。
    fireEvent.click(
      await screen.findByRole('button', { name: '播放 00:58 – 01:40 原声' }),
    )
    fireEvent.click(screen.getByRole('button', { name: '暂停 00:58 – 01:40 原声' }))

    const audio = screen.getByTestId('transcript-audio') as HTMLAudioElement
    fireEvent(audio, new Event('loadedmetadata'))
    // 迟到的元数据不再 seek 开播，按钮保持「播放」态。
    expect(audio.currentTime).toBe(0)
    expect(
      screen.getByRole('button', { name: '播放 00:58 – 01:40 原声' }),
    ).toBeInTheDocument()
  })

  it('播到块尾自动停，再点当前行则暂停', async () => {
    mockTranscript(false)

    renderView('raw')

    const play = await screen.findByRole('button', {
      name: '播放 00:00 – 00:58 原声',
    })
    const audio = screen.getByTestId('transcript-audio') as HTMLAudioElement

    fireEvent.click(play)
    expect(
      screen.getByRole('button', { name: '暂停 00:00 – 00:58 原声' }),
    ).toBeInTheDocument()
    // 越过块尾的 timeupdate 触发自停。
    audio.currentTime = 59
    fireEvent(audio, new Event('timeupdate'))
    expect(
      screen.getByRole('button', { name: '播放 00:00 – 00:58 原声' }),
    ).toBeInTheDocument()

    // 再点开播后手动点暂停，回到「播放」态。
    fireEvent.click(screen.getByRole('button', { name: '播放 00:00 – 00:58 原声' }))
    fireEvent.click(screen.getByRole('button', { name: '暂停 00:00 – 00:58 原声' }))
    expect(
      screen.getByRole('button', { name: '播放 00:00 – 00:58 原声' }),
    ).toBeInTheDocument()
  })
})
