import { Command } from 'cmdk'
import { useEffect, useState } from 'react'
import { listMeetings, type Meeting } from '../api/client'
import { Icon } from './Icon'

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
}

/** ⌘K 命令面板：搜索并跳转会议，或执行新建/导航；cmdk 无头库＋现有 token 皮肤。 */
export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const [meetings, setMeetings] = useState<Meeting[]>([])

  useEffect(() => {
    if (!open) {
      return
    }
    let stale = false
    listMeetings()
      .then((items) => {
        if (!stale) {
          setMeetings(items)
        }
      })
      // 面板里的会议清单是便利功能，取不到就只剩导航项，不打扰
      .catch(() => {})
    return () => {
      stale = true
    }
  }, [open])

  const go = (hash: string) => {
    window.location.hash = hash
    onClose()
  }

  return (
    <Command.Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          onClose()
        }
      }}
      label="命令面板"
    >
      <Command.Input placeholder="搜索会议，或输入命令…" />
      <Command.List>
        <Command.Empty>没有匹配的结果</Command.Empty>
        {meetings.length > 0 && (
          <Command.Group heading="会议">
            {meetings.map((meeting) => (
              <Command.Item
                key={meeting.id}
                value={`${meeting.title} ${meeting.id}`}
                onSelect={() => go(`#/meetings/${meeting.id}`)}
              >
                <Icon name="meetings" size={13} />
                <span className="cmdk-item-label">{meeting.title}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}
        <Command.Group heading="操作与导航">
          <Command.Item value="新建会议 new meeting" onSelect={() => go('#/new')}>
            <Icon name="plus" size={13} />
            <span className="cmdk-item-label">新建会议</span>
          </Command.Item>
          <Command.Item value="会议列表 meetings list" onSelect={() => go('#/')}>
            <Icon name="meetings" size={13} />
            <span className="cmdk-item-label">会议列表</span>
          </Command.Item>
          <Command.Item
            value="声纹库 voiceprints"
            onSelect={() => go('#/voiceprints')}
          >
            <Icon name="voiceprints" size={13} />
            <span className="cmdk-item-label">声纹库</span>
          </Command.Item>
          <Command.Item value="词库 hotwords" onSelect={() => go('#/hotwords')}>
            <Icon name="hotwords" size={13} />
            <span className="cmdk-item-label">词库</span>
          </Command.Item>
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  )
}
