# V0.4 作品发现：方案与数据缺口

2026-10-29。当前消息未附 Iwara 截图，按三分区信息架构与现有浅色 React 风格独立实现。

## 第一阶段：最新 MOD（本轮）

- 复用 SQLite 分页、游戏/搜索/分级过滤及统一 PreviewCard/详情高清画廊。
- 默认来源发布排序；提供最近来源更新、本地首次发现两种模式。更新时间缺失的作品不进入最近更新模式，不使用 modified_at 替代。
- created_at 表示作品来源发布，不表示工具本次首次发现；first_seen_at/first_seen 事件仅表示本地发现。
- updated_at 是已保存的来源更新时间。只有 mod_events.source_updated 才能标为“已记录来源更新”；首次获得 updated_at 不能声称本次检测到版本更新。
- 展示当前游戏范围最近一条 sync_runs 记录的时间与状态；全部游戏下是任一游戏最近一条，不表示六游戏同时完成。失败不能显示为成功，无记录显示暂无同步记录。
- 明示本地收录数量和覆盖完整性未验证；不将 797 条当作来源全量。同步 success 与来源覆盖完整性分开。
- 导航提供“订阅动态 / 最新 MOD / 热门 MOD”，后两阶段禁用并注明未开放，不展示伪造内容。
- 本阶段只读，不新增表、不运行迁移或同步。

## 当前审计

本地四张表：mods、user_states、mod_events、sync_runs。

| 数据 | 当前结果 |
|---|---:|
| MOD 总数 | 797 |
| created_at 非空 | 797 |
| updated_at 非空 | 357 |
| author_id 非空 | 797 |
| first_seen 事件 | 797 |
| metadata_changed 事件 | 1 |
| source_updated 事件 | 0 |

最新同步记录：游戏 23012，2026-10-27T06:47:14.245081Z 完成，status=success。不是覆盖证明。

本地 mods 无作者关注表，也无点赞/浏览/下载列；已保存 raw_metadata_json 中未找到对应计数字段，当前标准化函数不保留这些计数。

官方实时验证仅 2 次请求、3 条作品，不下载图片：

- `https://gamebanana.com/apiv11/Mod/ListFilterConfig` 列出 Generic_Newest、Generic_LatestUpdated、Generic_MostLiked、Generic_MostViewed、Generic_MostDownloaded 等排序。
- `Mod/Index` 原神第一页，`_nPerpage=3`、`_sSort=Generic_MostLiked`：HTTP 200，三个游戏 ID 均 8552，点赞 7025、6600、5211，样本内递减；实际有 `_nLikeCount`、`_nViewCount`，没有下载计数。
- 累计计数不能推导近 7 天热度。MostViewed/MostDownloaded 本轮只确认配置声明，没有执行对应排序请求，下载数具体字段尚未确认。
- 结果保存在忽略的 logs/discovery_audit_20261029_070701.json。网页不自动请求此接口。

## 第二阶段：订阅动态（后续独立任务）

1. 使用增量迁移增加 author_subscriptions，主键 `(source, author_id)`；可存关注时间与已知作者名称/URL。作者标识来自来源，不能按名称去重。
2. 不将关注表绑定至某条 MOD，不因作品更新或缺失删除关注；普通 importer 不操作此表。保护既有 user_states。
3. 迁移与关注/取消关注均采用现有 Backup API、事务、回滚机制；执行前备份，迁移后比对原 MOD 数和人工状态，先用临时数据库测试。
4. API 增加明确的本机写入端点，校验 Host/Origin、参数与身份；关注状态存 SQLite，前端状态不作为唯一存储。
5. 动态通过本地 SQL 连接关注表、mods、mod_events，过滤和排序先于分页。无关注时显示空状态，不为每张卡片请求来源 API。
6. 来源新发布根据 created_at 展示；本地 first_seen 作为发现信息，不能冒充新发布。更新复用 source_updated 事件及 occurred_at，metadata_changed 不当作版本更新。版本文本和来源更新时间分别保留。
7. 继续复用卡片和详情，浏览分级偏好与人工审核分开。

## 第三阶段：热门 MOD（后续独立任务）

1. 先对 MostViewed/MostDownloaded 做有界样本验证，确认实际字段与缺失行为，不扩大全库采集。
2. 保存真实累计计数及采样 UTC 时间，可用独立 mod_metrics_snapshots 表通过联合作品身份关联，并单独增量迁移。
3. 初版只能标注“本地样本累计点赞/浏览排行”，不能叫来源全站榜或近 7 天榜。热门来源样本可能还不在本地，是否允许入库需下一阶段明确授权。
4. 近 7 天指标需要相隔时间的可靠快照或官方明确的时间窗口接口；没有足够证据时不提供。不得把近 7 天发布作品的累计点赞称为近 7 天新增点赞。
5. 指标缺失保留 NULL，不生成假数值、不加伪统计分类数量。与同步采集分离，避免破坏人工状态、分级证据及高清图片。

每个阶段单独测试、验收；本轮不提前增加关注写入、热度迁移或自动调度。
