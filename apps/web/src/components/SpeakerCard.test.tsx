import { act, fireEvent, render, screen, within } from '@testing-library/react'
import type { ReviewCard } from '../api/client'
import { resetPlaybackForTests } from './clipPlayback'
import { SpeakerCard } from './SpeakerCard'

/** 可触发事件的 WaveSurfer 桩：jsdom 播不了真音频，只验证调用与状态 */
interface MockSurfer {
  handlers: Record<string, Array<(...args: unknown[]) => void>>
  on: ReturnType<typeof vi.fn>
  un: ReturnType<typeof vi.fn>
  destroy: ReturnType<typeof vi.fn>
  play: ReturnType<typeof vi.fn>
  pause: ReturnType<typeof vi.fn>
  setTime: ReturnType<typeof vi.fn>
  getDuration: ReturnType<typeof vi.fn>
  exportPeaks: ReturnType<typeof vi.fn>
  emit: (event: string, ...args: unknown[]) => void
}

const surfers = vi.hoisted(() => [] as MockSurfer[])

vi.mock('wavesurfer.js', () => ({
  default: {
    create: vi.fn(() => {
      const handlers: Record<string, Array<(...args: unknown[]) => void>> = {}
      const surfer: MockSurfer = {
        handlers,
        on: vi.fn((event: string, cb: (...args: unknown[]) => void) => {
          ;(handlers[event] ??= []).push(cb)
        }),
        un: vi.fn(),
        destroy: vi.fn(),
        play: vi.fn(),
        pause: vi.fn(),
        setTime: vi.fn(),
        getDuration: vi.fn(() => 20),
        exportPeaks: vi.fn(() => [
          Array.from({ length: 200 }, (_, i) => (i % 2 === 0 ? 0.8 : 0.3)),
        ]),
        emit(event: string, ...args: unknown[]) {
          for (const cb of handlers[event] ?? []) {
            cb(...args)
          }
        },
      }
      surfers.push(surfer)
      return surfer
    }),
  },
}))

function makeCard(clusterId: string): ReviewCard {
  return {
    cluster_id: clusterId,
    total_seconds: 12,
    suggested_person_id: null,
    suggested_display_name: null,
    suggested_tier: null,
    // 片段 2s–6s：span 4 秒，波形点击按相对位置换算
    sample_clips: [{ start_seconds: 2, end_seconds: 6, text: '测试片段' }],
    text: '测试片段',
  }
}

function cardProps(card: ReviewCard) {
  return {
    meetingId: 'm1',
    card,
    otherClusterIds: [],
    people: [],
    anonymousIndex: 1,
    clusterLabels: {},
    draft: undefined,
    onChange: () => {},
  }
}

/** 让隐藏 WaveSurfer 完成解码，片段波形（SVG）才会渲染 */
function decodeAll() {
  act(() => {
    for (const surfer of surfers) {
      surfer.emit('decode')
    }
  })
}

function waveOf(cardEl: HTMLElement): SVGSVGElement {
  const wave = cardEl.querySelector('svg.clip-wave')
  if (wave === null) {
    throw new Error('片段波形未渲染')
  }
  vi.spyOn(wave, 'getBoundingClientRect').mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 192,
    bottom: 24,
    width: 192,
    height: 24,
    toJSON: () => ({}),
  } as DOMRect)
  return wave as SVGSVGElement
}

beforeEach(() => {
  surfers.length = 0
  resetPlaybackForTests()
})

describe('试听片段播放器', () => {
  it('点击波形按相对位置跳转并开始播放，显示片段内进度', () => {
    render(<SpeakerCard {...cardProps(makeCard('S1'))} />)
    decodeAll()

    const cardEl = screen.getByTestId('speaker-card-S1')
    const wave = waveOf(cardEl)
    // 中点：2s + 0.5 × 4s = 4s
    fireEvent.click(wave, { clientX: 96 })

    expect(surfers[0].setTime).toHaveBeenCalledWith(4)
    expect(surfers[0].play).toHaveBeenCalledTimes(1)
    expect(within(cardEl).getByText('0:02.0 / 0:04.0')).toBeInTheDocument()
    expect(
      within(cardEl).getByRole('button', { name: /暂停 0:02\.0–0:06\.0/ }),
    ).toBeInTheDocument()
  })

  it('播放中进度随 timeupdate 前进；暂停保留播放头，再播续播不回起点', () => {
    render(<SpeakerCard {...cardProps(makeCard('S1'))} />)
    decodeAll()

    const cardEl = screen.getByTestId('speaker-card-S1')
    fireEvent.click(
      within(cardEl).getByRole('button', { name: /试听 0:02\.0–0:06\.0/ }),
    )
    expect(surfers[0].setTime).toHaveBeenCalledWith(2)

    act(() => {
      surfers[0].emit('timeupdate', 3.5)
    })
    expect(within(cardEl).getByText('0:01.5 / 0:04.0')).toBeInTheDocument()

    // 暂停：播放头与进度保留在原位
    fireEvent.click(within(cardEl).getByRole('button', { name: /暂停/ }))
    expect(surfers[0].pause).toHaveBeenCalledTimes(1)
    expect(within(cardEl).getByText('0:01.5 / 0:04.0')).toBeInTheDocument()

    // 续播：只再 play，不重新 setTime 回片段开头
    fireEvent.click(within(cardEl).getByRole('button', { name: /试听/ }))
    expect(surfers[0].play).toHaveBeenCalledTimes(2)
    expect(surfers[0].setTime).toHaveBeenCalledTimes(1)
  })

  it('全局同时只播一条：播 B 会先暂停 A（跨卡片）', () => {
    render(
      <>
        <SpeakerCard {...cardProps(makeCard('A'))} />
        <SpeakerCard {...cardProps(makeCard('B'))} />
      </>,
    )
    decodeAll()

    const cardA = screen.getByTestId('speaker-card-A')
    const cardB = screen.getByTestId('speaker-card-B')

    fireEvent.click(within(cardA).getByRole('button', { name: /试听/ }))
    expect(surfers[0].play).toHaveBeenCalledTimes(1)
    expect(surfers[0].pause).not.toHaveBeenCalled()

    // 点 B 的波形直接从中点播：A 被总线暂停
    fireEvent.click(waveOf(cardB), { clientX: 96 })
    expect(surfers[0].pause).toHaveBeenCalledTimes(1)
    expect(surfers[1].play).toHaveBeenCalledTimes(1)
    // A 的按钮回到「试听」（已暂停），B 显示「暂停」
    expect(within(cardA).getByRole('button', { name: /试听/ })).toBeInTheDocument()
    expect(within(cardB).getByRole('button', { name: /暂停/ })).toBeInTheDocument()
  })

  it('片段播到 end_seconds 停止并复位', () => {
    render(<SpeakerCard {...cardProps(makeCard('S1'))} />)
    decodeAll()

    const cardEl = screen.getByTestId('speaker-card-S1')
    fireEvent.click(within(cardEl).getByRole('button', { name: /试听/ }))
    act(() => {
      surfers[0].emit('timeupdate', 6.05)
    })

    expect(surfers[0].pause).toHaveBeenCalledTimes(1)
    expect(within(cardEl).getByRole('button', { name: /试听/ })).toBeInTheDocument()
    expect(within(cardEl).queryByText(/\/ 0:04\.0/)).not.toBeInTheDocument()
  })
})
