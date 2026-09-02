import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { useRef } from 'react'
import type { ReviewCard } from '../api/client'
import { resetPlaybackForTests } from './clipPlayback'
import { SpeakerCard } from './SpeakerCard'

// 整页只有一个 <audio> 与一份后端峰值：卡片不再各自解码整场音频。
const PEAKS = Array.from({ length: 200 }, (_, i) => (i % 2 === 0 ? 0.8 : 0.3))
const DURATION = 20

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

/** 模拟 SpeakerReview：一个共享 audio 元素 + 峰值，传给若干张卡 */
function Harness({ cards }: { cards: ReviewCard[] }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  return (
    <>
      <audio ref={audioRef} data-testid="review-audio" />
      {cards.map((card, index) => (
        <SpeakerCard
          key={card.cluster_id}
          meetingId="m1"
          card={card}
          otherClusterIds={[]}
          people={[]}
          anonymousIndex={index + 1}
          clusterLabels={{}}
          draft={undefined}
          onChange={() => {}}
          audioRef={audioRef}
          peaks={PEAKS}
          duration={DURATION}
        />
      ))}
    </>
  )
}

function setup(...ids: string[]) {
  render(<Harness cards={ids.map(makeCard)} />)
  const audio = screen.getByTestId('review-audio') as HTMLAudioElement
  const play = vi.spyOn(audio, 'play')
  const pause = vi.spyOn(audio, 'pause')
  return { audio, play, pause }
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

function tick(audio: HTMLAudioElement, time: number) {
  act(() => {
    audio.currentTime = time
    fireEvent(audio, new Event('timeupdate'))
  })
}

beforeEach(() => {
  resetPlaybackForTests()
})

describe('试听片段播放器', () => {
  it('点击波形按相对位置跳转并开始播放，显示片段内进度', () => {
    const { audio, play } = setup('S1')

    const cardEl = screen.getByTestId('speaker-card-S1')
    // 中点：2s + 0.5 × 4s = 4s
    fireEvent.click(waveOf(cardEl), { clientX: 96 })

    expect(audio.currentTime).toBe(4)
    expect(play).toHaveBeenCalledTimes(1)
    expect(within(cardEl).getByText('0:02.0 / 0:04.0')).toBeInTheDocument()
    expect(
      within(cardEl).getByRole('button', { name: /暂停 0:02\.0–0:06\.0/ }),
    ).toBeInTheDocument()
  })

  it('播放中进度随 timeupdate 前进；暂停保留播放头，再播续播不回起点', () => {
    const { audio, play, pause } = setup('S1')

    const cardEl = screen.getByTestId('speaker-card-S1')
    fireEvent.click(
      within(cardEl).getByRole('button', { name: /试听 0:02\.0–0:06\.0/ }),
    )
    expect(audio.currentTime).toBe(2)

    tick(audio, 3.5)
    expect(within(cardEl).getByText('0:01.5 / 0:04.0')).toBeInTheDocument()

    // 暂停：播放头与进度保留在原位
    fireEvent.click(within(cardEl).getByRole('button', { name: /暂停/ }))
    expect(pause).toHaveBeenCalledTimes(1)
    expect(within(cardEl).getByText('0:01.5 / 0:04.0')).toBeInTheDocument()

    // 续播：只再 play，不 seek 回片段开头
    fireEvent.click(within(cardEl).getByRole('button', { name: /试听/ }))
    expect(play).toHaveBeenCalledTimes(2)
    expect(audio.currentTime).toBe(3.5)
  })

  it('全局同时只播一条：播 B 会先暂停 A（跨卡片，共用同一个 audio）', () => {
    const { audio, play, pause } = setup('A', 'B')

    const cardA = screen.getByTestId('speaker-card-A')
    const cardB = screen.getByTestId('speaker-card-B')

    fireEvent.click(within(cardA).getByRole('button', { name: /试听/ }))
    expect(play).toHaveBeenCalledTimes(1)
    expect(pause).not.toHaveBeenCalled()

    // 点 B 的波形直接从中点播：A 被总线暂停，播放头切到 B 的片段
    fireEvent.click(waveOf(cardB), { clientX: 96 })
    expect(pause).toHaveBeenCalledTimes(1)
    expect(play).toHaveBeenCalledTimes(2)
    expect(audio.currentTime).toBe(4)
    expect(within(cardA).getByRole('button', { name: /试听/ })).toBeInTheDocument()
    expect(within(cardB).getByRole('button', { name: /暂停/ })).toBeInTheDocument()

    // A 的 timeupdate 监听已解除：B 在播时的时间更新不该让 A 显示进度
    tick(audio, 5)
    expect(within(cardA).queryByText(/\/ 0:04\.0/)).not.toBeInTheDocument()
    expect(within(cardB).getByText('0:03.0 / 0:04.0')).toBeInTheDocument()
  })

  it('片段播到 end_seconds 停止并复位', () => {
    const { audio, pause } = setup('S1')

    const cardEl = screen.getByTestId('speaker-card-S1')
    fireEvent.click(within(cardEl).getByRole('button', { name: /试听/ }))
    tick(audio, 6.05)

    expect(pause).toHaveBeenCalledTimes(1)
    expect(within(cardEl).getByRole('button', { name: /试听/ })).toBeInTheDocument()
    expect(within(cardEl).queryByText(/\/ 0:04\.0/)).not.toBeInTheDocument()
  })

  it('没有峰值时不画波形，试听照常可用', () => {
    function NoPeaks() {
      const audioRef = useRef<HTMLAudioElement>(null)
      return (
        <>
          <audio ref={audioRef} data-testid="review-audio" />
          <SpeakerCard
            meetingId="m1"
            card={makeCard('S1')}
            otherClusterIds={[]}
            people={[]}
            anonymousIndex={1}
            clusterLabels={{}}
            draft={undefined}
            onChange={() => {}}
            audioRef={audioRef}
            peaks={null}
            duration={0}
          />
        </>
      )
    }
    render(<NoPeaks />)
    const audio = screen.getByTestId('review-audio') as HTMLAudioElement
    const play = vi.spyOn(audio, 'play')

    const cardEl = screen.getByTestId('speaker-card-S1')
    expect(cardEl.querySelector('svg.clip-wave')).toBeNull()
    fireEvent.click(within(cardEl).getByRole('button', { name: /试听/ }))
    expect(play).toHaveBeenCalledTimes(1)
    expect(audio.currentTime).toBe(2)
  })
})
