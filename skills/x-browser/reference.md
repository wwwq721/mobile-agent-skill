# bw 内里（改代码 / 排障时看）

主脚本 `/var/minis/skills/x-browser/bw`（软链 `/usr/local/bin/bw`）。只走无障碍节点 + 系统截屏：
不装插件、不连调试口、不依赖 App 版本。

> 换机器部署、几何实测值、改代码的连带项 → [迁移.md](迁移.md)。这份只讲"现在是怎么实现的"。

## 两条通道

| 通道 | 命令 | 读取成本 | 登录态 | 说明 |
|---|---|---|---|---|
| app 内置 WebView（`minis-browser-use` 子进程） | `bw fast` | 读完 **8–10ms**；打开要等渲染：本机实测 1.8s（example.org）/ 3.4s（example.com）/ 30.7s（iana.org） | 无，独立 cookie | 不动屏幕、不产生标签 |
| 外置 X 浏览器（无障碍） | `bw go/tap/type/read` | 350ms/次 dump | **用户的** | 真交互，屏幕上看得见 |

打开页面两条路一样要等渲染（1.5–2.6s，重页面 4.5s），差的是"读完"。故意保留两条：只读走 `fast`，
要登录态走 `go`。判断错也不亏——`fast` 正文 <200 字就是登录墙，换 `go` 即可。

## 数据流

```
dump()          android-a11y-cli ui dump（**不要加 --compact**，它丢 packageName/bounds）
 └ web_nodes()  只留网页正文区（TOP/BOTTOM 由第一帧实测：本机 295/2574，旧机 240/2255）
 └ page_items() 去重、按 (y//8, x) 排成阅读顺序，剔掉页面外壳词（CHROME）
 └ render()     先打 flag() 的告警行，再打标题行 + 正文
sig()           (地址栏标题, 块数, 前 12 块文字)；页面"变没变"全靠它
settle()        等"变了 + 连续两次一样 + 内容够（≥300 字，或已等 4.2s 且 ≥80 字）"
patience()      仍不足 80 字就再等两口气，别把空壳交出去
flag()          ⛔ 拦截页 / ⛔ 像是登录墙 / ⚠ 0 字 / ⚠ 下载弹窗 / ⚠ 这页是接口返回的 JSON（模型按前缀匹配，别改字）
```

## 命令 → 机制

| 命令 | 怎么做的 |
|---|---|
| `go` | 默认**复用我开的页**（当前标题在记账里就走地址栏）；否则 intent `VIEW` + `package=` 直达。**intent 只在 Minis 在前台时送得到**（浏览器在前台＝Minis 后台＝系统静默 cancel 后台启动）→ 新开页时先 `bring_minis_front()`（Recents → 点 Minis 卡片）把自己切回来再发 intent；切不回来或 `BW_NO_FRONT=1` 就走"面板点新建标签 → 地址栏"。URL 含 `#`/`;` 强制走地址栏。只有确认落地（内容变了 / 地址栏已是目标域名）才 `note_tab`，否则 exit 3 且不记账 |
| `read` | 纯节点；`-n` 复用 `scroll_n`，滑完读停下的那屏 |
| `tap` | 精确→前缀→包含匹配；命中多个时按"完全匹配 / 非标题 / 可点"打分**自动选最上那个**并在括号里报其余候选（只有敏感词表里的动作才列候选停下，等 `--nth`）；点完 settle，没变化 **exit 3** |
| `type` | 点框 → 等 editable&focused → `input text --node <id>`；`--into` 还会看框上下 90px 里的提示词 |
| `submit` | 键盘搜索键 → 同排按钮 → 叫出键盘再按；页面真变了才算成功 |
| `find` | `go` 搜索 → `result_titles()` 挑"像结果"的（≥14 字、可点、下面跟摘要、不是搜索词回声）→ 点第 n 条；`--site` 拼进查询串并只认该来源 |
| `tabs` | 无参读本地记账；带参进标签管理点卡片切过去，用 `bar_text` 自证 |
| `close` | 进面板核对卡片（`before/after` 各数一次；数到 0 张先重开一次，仍 0 → `noview` 不动账）→ 只关记账里对得上的 → `dismiss_dialog()` 清弹窗 → 复位拟人。**默认不回桌面**（`--home` 才回）；没关干净 exit 3 且保留记录 |

## 退出码契约

`0` 成功｜`3` 效果不确定（没变化 / 没打开 / 不在前台没关成）｜`2` 硬失败（找不到目标、无障碍挂了）。
`close` 另有内部状态 `ok / partial / changed / env / noview / dry`（`dry` = `BW_CLOSE_FORCE=0` 只核对不点击）。
`a && b` 因此会停在出事那步；`die()` 在退出前会 `render(dump())` 一次——失败必须带屏，否则模型要多花一轮。

## 记账 `/var/minis/shared/bw/session.json`（跨会话共用）

```json
{"tabs": [{"title": "...", "ts": 0, "tries": 0}], "active": 0, "last": "...", "human_until": 0}
```

- 放 `shared/` 是因为标签属于**浏览器**，不属于某个会话；放会话 workspace 里，别的会话就看不见、关不掉（老位置 `workspace/bw/session.json` 会在首次读取时自动搬过来）。
- 一条标签一条记录 `{"title", "ts"}`（`close` 核对失败时补 `tries`，≥3 就丢弃该条），`tabs` 最多 20 条；`active` 指向"我开的那一个"；`last` 是最后停留页。
- 点结果常在新标签打开 → `retitle_active()` **追加**新标题而不是改名，宁可多关一次也不漏关。
- `go` 复用我开的页：走地址栏（同一标签）时用 `rename_active()` **就地改名**；不确定同一标签时才 `retitle_active()` 追加。不记账的卡永远关不掉。
- 地址栏失败会留下联想浮层，`_bar_cleanup()` 负责按一次 back 收掉；不收会让下一次 `go` 假成功（迁移 §4.7）。
- `human_until` 是拟人粘性的截止时间（15 分钟，每次用续期；`close` 归零）。
- **没有配额机制**（旧版的 `quota[title]` 已删）：关不关得掉靠 `close` 逐次核对，`tries>=3` 才放弃该条记录。

## 本机事实（换机/换版本要重测）

- 包名 `com.mmbox.xbrowser`；回前台只认 `com.mmbox.xbrowser/.BrowserActivity`（只给 package 会 `no_handler`）。
- 输入法 `com.sohu.inputmethod.sogou`，键盘是**浮层**：窗口 bottom 不缩，只能靠 dump 里有没有 `*inputmethod*` 判断键盘开没开。
- 键盘右下角是"搜索/前往/开始"，纵坐标**换机就变**：代码先试本机的 `H-186`（Sogou「开始」），再退旧机 `H-100`。**键盘没开时这个位置是底部工具栏的"主页"**，按之前必须确认键盘在。
- 屏幕尺寸首帧实测，不再写死；换机后的实测值见 [迁移.md](迁移.md) §三。截图走 `scr shot`。
- 底部工具栏 x 分段：本机 16–265–514–764–1014–1264，旧机 0–225–435–645–855–1065。
- 换机差异与改造清单 → [迁移.md](迁移.md)。

## 踩过的坑

1. `ui dump --compact` 丢 `packageName`/`bounds`，按坐标过滤会全空（症状：前台是浏览器却读到 0 块）。
2. `nodeId` 每次 dump 都变：取节点和用它必须同一个进程里连着做，跨 dump 用会 `ACTION_SET_TEXT failed`。
3. 地址栏是自绘输入框：`input text` 必须带 `--node`；提交要按**键盘右下角**，右边那个小图标是开新标签。
4. WebView 输入框用 ACTION_CLICK 只给焦点、不弹键盘；要弹键盘得用坐标点。
5. bing 结果页滚动后节点不更新 → `scroll` 会报"节点没跟着动"，别当到底了，要 `bw shot`。
6. 知乎/微博正文是登录墙：节点只剩导航条，`flag()` 会标出来，别反复读。

## 想扩的时候

- 新动作照 `cmd_*` 写：`dump()` → 改 → `settle(before)` → 一行结论 + `render()`；失败用 `die()`（自带回屏）。
- 别在命令里 print 中间过程；`-q/--brief` 只留一行是链式执行的纪律。
- 危险动作（关闭全部、收藏、清历史）不做；要做得先问用户。
