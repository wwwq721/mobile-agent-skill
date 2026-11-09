---
name: phone-browser
description: 在用户手机上用真实浏览器（X 浏览器 com.mmbox.xbrowser）打开、读取、点击网页，保留登录态、拿到真实 DOM。凡"在手机上打开/看/点某个网站"先用本技能，不要用无障碍慢慢点。
version: 2.2.0
---

# 手机浏览器（真实浏览器 + 页面内 JS）

**目的**：让 AI 像人一样用用户手机上那个浏览器 —— 登录态还在，表单、SPA、弹层都是真的。
手段：浏览器里跑一个用户脚本，长轮询沙箱的 `127.0.0.1:8765`，把命令送进页面 `eval`，结果回传。不是截图猜坐标，也不是无障碍点按钮。

**范围**：只做四件事 —— **打开、读取、点击、填普通表单**（input/select/checkbox/textarea）。
超出这四件的一律"能用就用、不能就算"，不再投入：富文本编辑器会如实回 `fill_rejected` 而不是假装成功，够了。
判断标准：**这个改动让"打开/读取/点击"更快或更稳吗？**

## 先决条件

```bash
xb status        # ok  sv=3.9.1  tabs=1  pending=0  cache=0B
                 #   nosf6n1  就绪  https://…
```

- 没响应 → 桥没起：`sh skills/phone-browser/bridge/restart.sh`
- `没有标签` → 浏览器没开或已退到后台被杀（`android-open <url>` 拉起）
- 标签显示 `脚本旧(3.9.0)` → 那个标签跑旧脚本，刷新页面
- `后台` / `raf=0` → 页面被冻结，操作会用不了；把浏览器切到前台

## 怎么调用（默认 `xb`）

```bash
xb open 'https://example.com/' # 复用现有标签导航（默认）
xb open --new 'https://…'      # 保留旧页状态时新开一个（并排/对照/表单做到一半）
xb js 'document.title'          # 0.1s，只回值本身（出错才摊开细节）
xb text                         # 正文前 3000 字；text all 全文；text '#sel' 局部
xb snapshot                     # 紧凑：序号 · 标签 · 文字 · ref
xb snapshot --all               # 最多 200 条（默认 70）
xb snapshot --sel               # 连 CSS 路径；--text 连正文；--raw 原始 JSON
xb click '#submit'              # 也可以直接贴快照里的 ref
xb fill '#kw' '关键词'          # input/select/checkbox/textarea
```

- **ref 可以省前缀**：快照打印的 `1ywd0i5-vy0j76-our2vj:0` 直接贴，`xb` 自动补 `minis-ref:`。
- 输出体积实测（MineBBS，188 个可交互元素）：紧凑 **5.8K**，`--raw` 22.5K（差 4 倍）。**默认别加 `--sel`**。
- `xb --op-id ID <cmd>` 复用同一次操作编号重试；省略就是新操作。失败回包会给 `op_id`。
- 值里有引号、换行或大段代码时别和 shell 搏斗，写文件再发：
  ```bash
  curl -s -X POST http://127.0.0.1:8765/api/fill --data-binary @/tmp/b.json   # 正文是 JSON
  curl -s -X POST http://127.0.0.1:8765/api/raw  --data-binary @/tmp/code.js  # 正文是 JS 原文
  ```

## 硬规则

1. **默认复用标签，别让标签堆起来**：`xb open <url>` 有标签就导航它、没有才新开；`android-open` 是它内部的兜底，别直接调。
   ```bash
   xb open 'https://example.com/x'        # 复用
   xb open --new 'https://example.com/y'  # 需要保留旧页（表单填一半、滚动位置、对照两个页面）时
   ```
   **注意**：只有前台那个标签能执行 JS（后台的会被冻结，见硬规则 2），所以"并列"实际是「保留状态 + 来回切」，
   不是两个页同时跑命令。切标签只能由用户点，或用无障碍点标签栏。

   **标签里可能有用户在用的东西**（网站上的进行中流程、填到一半的表单）。所以：
   - 多标签时先 `xb js 'location.href'` 确认当前是哪一页，再动手 —— 桥只投给"最可见"那个标签，就是用户正在看的那页。
   - 要打开新页面而当前页是用户在用的，用 `xb open --new`，**不要**把用户那页导航掉。
   - 任务结束不要清空标签；只关自己开的、且确认无用的（见「已知限制」里为什么 JS 关不掉）。
2. **浏览器必须在前台**（息屏也算后台）。判据只有 `xb status` 的 `visible`/`raf`，别猜。
   `needs_foreground`(409) 是桥的保护，不是故障。要连续操作就把「打开→做→取」压进**同一条 shell 命令**。
3. **`click` 回包自带跳转结论**：`✓ 已落到 X` 或 `跳转中，预期 X`。后者是异步跳转的常态，别再点第二次；
   要确认就 `xb js 'location.href'`。**报 timeout 也不等于没点**——页面卸载会丢回包。
4. **别用"innerText 里没有"判断不存在**：没点开的弹层根本没进 DOM。先 `xb snapshot` 看 `~` 开头的弹层 → 点开 → 再读。
5. **一次多步合成一条 JS**，比逐步调用快一个数量级。`code` 是表达式，多语句要包起来：
   ```bash
   xb js '(async()=>{ const a=await (await fetch("/api/x")).json(); return a.n; })()'
   ```
   **跨导航做不到**：跳转会把这条 JS 一起卸载，之后隔 ~1.2s 再发下一条。

## 找元素

`xb snapshot` 每行是 `序号 标签 "文字" ref`，`~` 开头表示在 shadow DOM / 同源 iframe 里（**只能用 ref 点**，CSS 穿不透影子树）。

- 点的时候会自动滚到目标，不用先滚动。
- 要自己写选择器时用稳定属性（`[name=xx]`、`a[href*=yy]`），别用 nth-child。
- 全页元素都收，不按视口裁剪。

## 常用片段

```js
document.body.innerText.slice(0,3000)
[...document.querySelectorAll('a')].map(a=>[a.innerText.trim(),a.href]).filter(x=>x[0])
[...document.querySelectorAll('table tr')].map(tr=>[...tr.children].map(td=>td.innerText))
```

## 健康检查（按序，别瞎猜）

1. `xb status` → 有无标签、`raf` ≈30？（<8 = 冻结）、`脚本旧`?
2. 无标签 → 浏览器没开/被杀。`android-open` 拉起，或请用户切回
3. 有标签但 `raf=0` → 前台被别的 App 占着（包括息屏）
4. 桥死 → 读类命令会自己重启（静默）；`js`/`click`/`fill` 不会，报 `Failed to connect` 就手动 `sh bridge/restart.sh`
5. 脚本没跑 → 浏览器打开 `http://127.0.0.1:8765/xb.user.js` 重装（流程见 `references/internals.md`）

## 已知限制（都实测过，别浪费时间重试）

| 现象 / 错误 | 含义 | 唯一正确做法 |
|---|---|---|
| `bridge cache full` / `input_busy`（503） | 额度或正文通道满，**动作还没下发** | 只按**原 `op_id`** 重试 |
| `result_too_large`（413） | 单条结果超 4 MiB | 缩小范围：`xb text '#main'`、`xb snapshot` |
| `result_not_cached`（507） | 结果到了但额度满，**动作已执行** | 别用新编号重做；重新读页面状态 |
| `delivered:true` + `result unknown` | 页面领走了没回结果 | 先 `xb js 'location.href'` 核验，别盲重试 |
| `needs_foreground`（409） | 匹配的标签都报隐藏 | 切前台，或一条命令内做完 |
| `not_interactive` / `disabled element` | 元素不可见、尺寸 0、或真禁用 | 换元素，别重试同一个 |
| `no element` / `ambiguous selector` | 选择器 0 个或多个 | 用 `xb snapshot` 的 ref |
| `fill_rejected: 控件拒绝该值` | 控件没吃下这个值（含富文本） | **不重试**，读回看实际值再定 |
| 富文本编辑器（Lexical/Slate/ProseMirror） | 有自己的模型，外部写入被回滚 | **不在范围内**。点进去用真键盘，或用它自己的 API |
| 白屏 / `#root` 空 | 本机内核实测 **Chrome 76–87**：无 `:is()`、`Array.at`、`structuredClone`，顶层 `await` 要 89 | 怀疑内核，不是桥。UA 是伪装的 iOS 串，别看 UA |
| 标签越堆越多 | 每个 `android-open <url>` 都**新开**一个标签 | 用 `xb open <url>`（复用现有标签，没有才新开）；清空靠标签管理器「关闭全部」 |
| 页面死循环卡 15–20s | 单线程 | 等，或换标签 |

## 什么时候才需要无障碍

**操作页面完全不需要。** 桥是 127.0.0.1 的 HTTP + 页面内脚本，跟 AccessibilityService 无关。
只在「点浏览器自己的 UI」时才要：装脚本、关标签、删脚本——这些也可以让用户手点一次。
X 浏览器按钮坐标在 `skills/mobile-ops/references/xbrowser.md`。

## 深入

架构、选标签算法、自愈、协议、装脚本、安全边界：`references/internals.md`（只在改桥或排障到底时读）。
