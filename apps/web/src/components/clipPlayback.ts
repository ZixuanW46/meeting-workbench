/**
 * 试听独占总线：全局同一时刻只允许一条片段出声。
 * 每张卡各持一个 owner 标识，开播前 claim（会先停掉别人），
 * 自己暂停 / 播完 / 卸载时 release 只清掉自己的登记。
 */

type StopFn = () => void

let current: { owner: symbol; stop: StopFn } | null = null

/** 开始播放前调用：先暂停其他持有者，再登记自己的停止回调。 */
export function claimPlayback(owner: symbol, stop: StopFn): void {
  if (current !== null && current.owner !== owner) {
    try {
      current.stop()
    } catch {
      // 停掉旧播放失败不阻塞新播放
    }
  }
  current = { owner, stop }
}

/** 自己暂停 / 播完 / 卸载时调用：只清除自己登记的项。 */
export function releasePlayback(owner: symbol): void {
  if (current?.owner === owner) {
    current = null
  }
}

/** 测试用：清空登记，避免用例间串音。 */
export function resetPlaybackForTests(): void {
  current = null
}
