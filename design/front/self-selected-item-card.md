# Self-Selected Item Card

本文档是 `Self-Selected` 股票卡片的前端维护入口。后续如果修改卡片样式、信息层级、交互反馈或跳转行为，先读本文，再改代码；改完后同步更新本文。

## 目标

当前 `Self-Selected` 页面会承载大量股票条目，卡片设计的重点不是做重，而是让用户在高密度列表里更快完成四件事：

- 一眼识别股票代码、名称、市场
- 快速判断该股票是否已经加入 `Application Analysis`
- 在普通自选分组里，快速把股票加入 `target` 系统分组
- 直接看到这个股票归属的行业 / 概念 / 风格
- 明确知道整卡不会跳转，只有右上角分析按钮会跳到分析页

因此卡片被设计成紧凑的 `signal card`，而不是普通列表行。

## 代码入口

核心文件：

- [item-row.tsx](/F:/dev-repo/mp4-to-word-new/frontend/src/views/self-selected/components/item-row.tsx)

关联文件：

- [index.tsx](/F:/dev-repo/mp4-to-word-new/frontend/src/views/self-selected/index.tsx)
- [constants.ts](/F:/dev-repo/mp4-to-word-new/frontend/src/views/self-selected/lib/constants.ts)
- [edit-item-notes-dialog.tsx](/F:/dev-repo/mp4-to-word-new/frontend/src/views/self-selected/components/edit-item-notes-dialog.tsx)

## 结构说明

`item-row.tsx` 当前分成 4 层视觉信息：

1. 顶部主信息区
   - `name + symbol + market + target_type` 放在同一条水平线上
   - `symbol` 用更弱的 mono 信息样式跟在名字后面
   - `market` / `target_type` 作为紧凑 badge 并列
   - 右上区域保留箭头与 `已加入` / `系统镜像` 状态

2. 中部板块归属区
   - 行业 / 概念 / 风格拆成 3 组 tag rail
   - 数据来自 F10 `stock-sectors`
   - 默认每组先显示少量摘要项，并展示总数
   - 若某组条目很多，通过单卡片内的“展开归属”查看全量，避免把整页撑得过高
   - 每个 chip 可带当日涨跌幅
   - 已发起请求但数据未返回时，显示 skeleton 占位，避免卡片高度抖动

3. 备注区
   - `notes` 用弱面板承载
   - 无备注时不强行占位

4. 底部 meta 区
   - 只保留轻量说明，不再放左侧色条
   - 目的是把空间让给真实股票信息
   - 如果当前卡片还没进 `Application Analysis targets`，这里提供 `加入 target` 快捷入口

5. 分组头信息
   - `Self-Selected target` 分组需要有系统 badge
   - 该分组必须明确写出“与 Application Analysis 双向同步”
   - 该分组不可删除
   - 该分组里的加号 tile 文案要更明确，如 `加入 target 分组`

## 交互约束

- 整张卡片不负责跳转
- 只有右上角箭头按钮负责进入 `application-analysis`
- 普通自选组卡片可以显示 `加入 target` 按钮，作为显式同步入口
- 右上角编辑按钮打开备注弹窗，保存后走 `PUT /api/self-selected/items/:item_id`
- 编辑 / 删除按钮必须阻止冒泡，不能触发跳转
- hover 时卡片上浮、边框增强、箭头前移
- hover / focus 时才显露操作按钮，避免平时视觉噪音太大

## 风格约束

- 保持与现有站内 `rounded + soft border + muted surface` 体系一致
- 不引入过重阴影或过高饱和背景，避免一页多卡时显脏
- 代码、市场、状态、板块归属四类信息必须在首屏可读，不依赖 notes
- 左侧竖向 accent bar 已取消，后续不要重新塞回去，除非整体设计方向变化
- 如果后续新增字段，优先补到行业 / 概念 / 风格区下方，不要先挤压标题区

## 修改清单

后续如果改这一块，至少同步检查：

- 卡片 hover / focus 是否仍清晰
- 跳转是否只由右上角箭头触发，而不是整卡触发
- `symbol / name / market / inAnalysis` 的层级是否被打乱
- `系统镜像` / `加入 target` 两类 target 相关提示是否同时清晰且不抢主信息
- 行业 / 概念 / 风格三组信息是否仍可快速扫描
- hover 操作按钮是否固定在右上角，且不遮挡标签区
- 展开 / 收起归属时是否只影响当前卡片，不拖垮整页扫描效率
- target 系统组是否仍不可删除，且 header / tile 文案仍能说明同步语义
- 小屏下是否仍能稳定换行和截断
- `item-row.tsx` 顶部维护注释是否仍指向本文档
- 本文档是否需要同步更新
