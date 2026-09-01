import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { exportUrls, type TranscriptVariant } from '../api/client'
import { Icon } from './Icon'

/** 结果页低频操作的折叠菜单：重新确认说话人 + 各导出口。
 *
 * 用 Radix 的 DropdownMenu 原语（shadcn 同款底层）自带焦点管理与键盘
 * 导航，皮肤走本站 Linear token，不引入 tailwind。
 */
export function ResultActionsMenu({
  meetingId,
  state,
  transcriptVariant,
  reopening,
  onReopen,
}: {
  meetingId: string
  state: string
  /** 导出转写跟随当前查看的口径 */
  transcriptVariant: TranscriptVariant
  reopening: boolean
  onReopen: () => void
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" className="btn" aria-label="更多操作">
          <Icon name="more" size={14} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="menu" align="end" sideOffset={6}>
          <DropdownMenu.Item asChild disabled={reopening}>
            <button type="button" className="menu-item" onClick={onReopen}>
              <Icon name="refresh" size={12} />
              重新确认说话人
            </button>
          </DropdownMenu.Item>
          <DropdownMenu.Separator className="menu-separator" />
          <DropdownMenu.Item asChild>
            <a
              className="menu-item"
              href={exportUrls.transcriptMd(meetingId, transcriptVariant)}
              download
            >
              <Icon name="download" size={12} />
              导出转写 MD
            </a>
          </DropdownMenu.Item>
          {state === 'READY' && (
            <>
              <DropdownMenu.Item asChild>
                <a className="menu-item" href={exportUrls.minutesMd(meetingId)} download>
                  <Icon name="download" size={12} />
                  导出纪要 MD
                </a>
              </DropdownMenu.Item>
              <DropdownMenu.Item asChild>
                <a
                  className="menu-item"
                  href={exportUrls.minutesDocx(meetingId)}
                  download
                >
                  <Icon name="download" size={12} />
                  导出纪要 DOCX
                </a>
              </DropdownMenu.Item>
            </>
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
