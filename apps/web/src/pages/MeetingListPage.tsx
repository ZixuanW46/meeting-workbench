import { Empty, Table, Typography } from 'antd'

// M0 占位：静态空列表。M1 改为从 GET /api/meetings 拉真实数据。
export interface MeetingRow {
  id: string
  title: string
  state: string
  created_at: string
}

const columns = [
  { title: '标题', dataIndex: 'title', key: 'title' },
  { title: '状态', dataIndex: 'state', key: 'state' },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at' },
]

export function MeetingListPage() {
  const meetings: MeetingRow[] = []
  return (
    <div>
      <Typography.Title level={5}>会议列表</Typography.Title>
      <Table<MeetingRow>
        rowKey="id"
        columns={columns}
        dataSource={meetings}
        locale={{ emptyText: <Empty description="还没有会议" /> }}
        pagination={false}
      />
    </div>
  )
}
