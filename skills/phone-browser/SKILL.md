---
name: phone-browser
description: 操控手机上的真实浏览器（Edge 或 X 浏览器，保留用户登录态）。用 MCP 工具 edge_js/edge_text/edge_click 执行页面内 JS、读全文、点元素，毫秒级。凡"在手机上打开/读/点某个网站"先用本技能，不要用无障碍慢慢点。
version: 1.1.0
---

# 手机浏览器（油猴桥：Edge / X 浏览器通用）

两台浏览器共用同一个桥和同一套工具：谁在前台、有页面在轮询，命令就投给谁。

手机 Edge 里跑一个油猴脚本，长轮询沙箱的 `127.0.0.1:8765`，把命令送进页面执行、结果送回。
**JS 在页面里跑，所以带用户登录态，且能拿 DOM —— 不是截图猜坐标。**

## 用法（MCP，已注册为 `edge`）

| 工具 | 作用 |
|---|---|
| `edge_snapshot` | **先调这个**：可见文字 + 可交互元素（含 CSS 选择器）+ 已弹出的浮层 |
| `edge_open {url}` | 在 Edge 打开网址并切前台；**会新开标签页**，非必要不用 |
| `edge_js {code}` | 执行 JS 表达式，返回字符串（对象自动 JSON） |
| `edge_text {selector?}` | 读正文（含 shadow DOM 与同源 iframe） |
| `edge_click {selector}` | 点击，等 700ms，**直接返回点击后的文字**；op_id 去重，重试不会重复点 |
| `edge_fill {selector, value}` | 填输入框并触发 input/change |
| `edge_status` | 看当前在线标签页 |

CLI 等价物：`edge js '<expr>'` / `edge text [css]` / `edge click '<css>'` / `edge status`。

## 常用片段

```js
document.title
document.body.innerText.slice(0, 3000)
[...document.querySelectorAll('a')].map(a=>[a.innerText.trim(), a.href]).filter(x=>x[0])
[...document.querySelectorAll('table tr')].map(tr=>[...tr.children].map(td=>td.innerText))
await new Promise(r=>setTimeout(r,2000)); document.body.innerText   // 等异步渲染
```

点击/填写尽量用稳定选择器（`[name=xx]`、`a[href*=yy]`），别用 nth-child 硬编码。

## 铁律：Edge 必须在前台

Android 会冻结后台 App，后台标签页的 JS 直接停摆 —— 这时 `/status` 里没有标签，命令 5 秒后超时。
**不要反复用 `edge_open` 去“叫醒”**：它每次都新开一个标签页，几轮下来用户能攒十几个。正确做法：
1. 首选让用户把 Edge 与 Minis **分屏**（两边都 resumed，最省事）；
2. 或把「打开 → 操作 → 取结果」压进**同一条 shell 命令**，期间 Edge 一直前台，只开一次标签；
3. 用户自己在 Edge 里时，直接 `edge_snapshot` 即可，不用 open。

调度细节：命令只投给「最近活跃」的那个标签（`url_contains` 可指定），5 秒没回应就换标签重试，最多 2 次。
**没标签回应且任务从未送达时，MCP 会自己把 Edge 拉起来**（`android-open` 带包名，会新开一个标签，约 3s），然后用上次的 URL 重试。
但有三条节流，尽量不堆窗口：
1. 目标页已经在 Edge 的标签列表里（只是被冻结）→ **不强开**，返回提示让你切前台/分屏；
2. 同一个 URL **2 分钟内只唤醒一次**（`/tmp/edge_wake.json`）；
3. 一次任务尽量中途不切 App —— 切走一次就可能要再唤醒一次。

**同一操作的 `op_id` 重试只等待、不重复执行**；已送达但页面没回的任务不会被重发，避免点两次。

标签页只能靠用户在标签页管理器里关：`window.close()` 在 Edge 里被拦截（实测无效）。所以别反复唤醒，一次任务尽量只唤醒一次。

## 弹层 / 异步内容

`innerText` 只能看到**已经挂载**的 DOM。像某高校开放平台的「申请提速」弹窗，是点了 ⚡ 才创建的，没点开之前页面里根本不存在。

固定套路：
1. `edge_snapshot` → 看 `interactive`（有哪些按钮可点，带选择器）和 `overlays`（有没有已经弹出来的浮层）
2. `edge_click` 那个触发元素 → 返回结果里直接带点击后的文字
3. 内容还没出来 → `edge_js 'await new Promise(r=>setTimeout(r,1500)); document.body.innerText'`

不要用「innerText 里没有 → 说明不存在」这种判断。

## 动作清单（实测，百度为例）

| 动作 | 怎么调 | 实测 |
|---|---|---|
| 打开网址 | `edge_open {url}` | 0.3s |
| 页面快照（文字/按钮/浮层） | `edge_snapshot` | 0.4s |
| 填搜索框 | `edge_fill {selector:'#index-kw', value:'…'}` | 0.3–0.5s |
| 点搜索按钮 | `edge_click {selector:'#index-bn'}` | 0.5–3s（含点击后等待） |
| 读结果列表 | `edge_js {code:"[...document.querySelectorAll('h3')].map(h=>h.innerText)"}` | 0.4s |
| 滚动 | `edge_js 'window.scrollBy(0,800)'` | 0.3s |
| 返回上一页 | `edge_js 'history.back()'` | 0.3s |

一次多步操作尽量合成**一条 JS**（设置输入 → 点击 → 等 2.5s → 取结果），一次往返拿全部，比逐步调快一个数量级。

## 空闲不掉线（v1.1 已修）

v1.0 有个真 bug：一次 `GM_xmlhttpRequest` 长轮询悬挂后没有看门狗，循环永久卡在 `await` 上 —— 表现为"页面开着、脚本还活着，但再也不轮询"，看起来像 30 秒空闲冻结。
v1.1 的修法：40 秒看门狗 abort 挂起的请求、`visibilitychange` 时立即重连、指数退避、心跳带上 `visible/focus`。
实测：**空闲 3 分钟后再调用仍是 0.4s**。

整页跳转（表单提交、链接）会让标签重载、脚本重新注入，新的 tab id 需要 1–3 秒；**打完 URL 不要立刻读，等 1–2 秒或用重试**（读结果失败就再发一次，别改逻辑）。

## 篡改猴 5.5.1 的权限要求（2026-10）

TM 5.5.1 起，「注入用户脚本」需要额外授权：Chrome 138+ 是扩展设置里的**「允许用户脚本」开关**，或**开发者模式**（官方 FAQ Q209）。
Edge 安卓这个版本**两个开关都没有**，表现就是时好时坏：有的页面能注入，`http://127.0.0.1:8765/minis.user.js` 有时会跳到 tampermonkey.net 的 "SCRIPT INSTALLATION" 说明页。
判断：如果脚本能跑（`edge_status` 有标签、`edge_js` 秒回），就说明这台机器已经放行，忽略那个说明页即可。

## 健康检查（30 秒定位）

出问题按这个顺序查，不要瞎猜：

1. `edge_status` → 有没有标签、`seen` 是不是很久以前
2. 在 Edge 里打开 `http://127.0.0.1:8765/minis.user.js`
   - 弹出篡改猴安装页（有脚本名/版本/安装按钮）→ 脚本没装，点安装
   - 显示英文 **"SCRIPT INSTALLATION … This page is used as an intermediate step"** → **篡改猴本身没了**（被 Edge 更新禁用/移除），去 Edge 菜单 → 扩展 重新装
   - 直接显示 JS 源码 → 篡改猴在但没接管 `.user.js`
3. `curl -s http://127.0.0.1:8765/status` → 桥是否活着

## 生命周期与坑

- **`android-open <url>` 不会打开 Edge**——走系统默认浏览器（本机是 X浏览器 `com.mmbox.xbrowser`）。拉 Edge 用带包名的 intent：`android-open 'intent://host/path#Intent;scheme=https;package=com.microsoft.emmx;end'`。
- **弹层/抽屉内容不在 `document.body.innerText` 里**，必须先点开再读（例：某高校开放平台的「申请提速」弹窗，里面的 `平台提供的联系邮箱` 不点开永远扫不到）。
- **`code` 是表达式**，多语句要包成 `(()=>{…})()`，`a=1;b=2` 会 SyntaxError。
- **桥**：`bridge.py` 监听 8765，MCP 启动时自动拉起（`ensure_bridge`）。App 被杀则桥断，脚本会每 2s 重试，下次调 MCP 自动恢复。
- **脚本只在装好后加载的标签页里跑**。装脚本前就开着的标签要刷新一次。
- 同一标签 SPA 跳转不影响；整页跳转会重建轮询（新 tab id），正常。
- Edge 被杀 / 标签被丢弃 → `edge_status` 返回空 tabs，重新打开页面即可。
- 页面是 `https` 时到 `127.0.0.1` 的请求走 GM_xmlhttpRequest，不受混合内容限制（已实测）。
- 别同时用无障碍去点同一个屏幕，会抢焦点。

## X 浏览器（内置脚本引擎，不需要篡改猴）

包名 `com.mmbox.xbrowser`（系统默认浏览器）。自带用户脚本管理器：设置 → 用户脚本。

**安装（唯一可靠方式）**：把脚本 URL 丢进浏览器，它识别出 `==UserScript==` 就弹「发现油猴脚本，是否安装？」→ 点"安装"。

```
android-open 'intent://127.0.0.1:8765/xb.user.js#Intent;scheme=http;package=com.mmbox.xbrowser;end'
# 源码：skills/phone-browser/xb/minis-xb.user.js（v3.0，由桥的 /xb.user.js 路由提供）
```

**实测结论（v5.6.4.1093）**
- `GM_xmlhttpRequest` **可用**（可跨域、可打 127.0.0.1），混合内容不拦 → 桥能跑，往返 ~0.2s。
- 元数据 `@match` 认域名/网址，`*://*/*` 与 `*` 也照跑；装完立刻自动执行。
- 官方文档：`https://www.xbext.com/docs/...`（注意必须带 `www.`，裸域 HTTPS 证书不匹配）。
- "自动执行"若要限定站点，是在脚本编辑页的**设置脚本执行方式**里选「自动执行」+ 填作用域，再点右上**保存**。

常用按钮坐标见 `skills/mobile-ops/references/xbrowser.md`。

**坑（都已踩过）**
- 每个 `android-open` intent 都会**新开标签页**，标签会堆积到几十个。要在页间跳转用 `edge_js 'location.href=...'`，别用 intent。
- 同一 URL 可能有多个标签同时轮询，后台的那个是冻结的，投过去必超时。桥已改为**优先选 `visible` 标签**（v1.1），仍失败就指定 `tab` id。
- 点会跳转的链接时，`edge_click` 常报 `timeout`：页面被卸载、结果包丢了，**动作其实已执行**，用 `edge_js 'location.href'` 确认落地页即可。
- 桥 v1.2：任务送达但页面没回执（长轮询被 abort）时，`eval` 会自动补投一次，不再白等。
- 标签管理器里点"关闭全部"图标（右下角那一摞）才是一次性清空，单个 × 要一个个点。
- 删脚本：列表每条右侧 ⋮（x≈996）点开后选题项就在同行右侧（x=737，禁用/编辑/删除/分享），删除无二次确认。

## 备选：无障碍（`pb.py`，已不推荐）

只在本机 X浏览器等场景用：`pb open/text/collect/tap`。慢且拿不到 DOM，Edge 场景一律走桥。

## 为什么不用 adb/CDP

本机 Edge 确有 `chrome_devtools_remote` socket，但 Android 10 的 SELinux 拒绝跨 App 连接（实测 `EACCES`），无 root 无解；`adb forward` 需插电脑。详见 2026-11-03 记忆。
