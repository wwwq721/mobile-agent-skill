# phone-browser 内部实现（SKILL.md 的深层附录）

只在**改桥 / 排障到底**时读。日常操作不需要。

## 组成

```
bridge/bridge.py       HTTP 桥，127.0.0.1:8765
bridge/xbops.py         所有下发的 JS 常量
bridge/restart.sh       按 /proc/*/cmdline 精确找进程重启
xb/minis-xb.user.js   页面用户脚本（@version 3.9.1）
xb/xb.sh  → /usr/local/bin/xb    curl 直调 /api/*（干活默认入口）
xb/xbfmt.py            把桥回的信封压成给 AI 读的紧凑文本（snapshot/text/status/js/click/fill）
```

路由：`/poll` `/presence` `/ack` `/result` `/status` `/xb.user.js`
+ `/api/{js,text,snapshot,click,fill}` + `/api/raw`（body 即 JS 原文，免转义）。
`click` 走页面侧点击并回 `/ack`，桥据此推断异步跳转是否落在 `expected_url`；`fill` 下发 `xbops.FILL_JS`
（checkbox/radio/select/contenteditable 的语义都在那份里，页面侧的简化版没有）。

## 选标签：看 rAF，不看 focus

WebView 里 `document.hasFocus()` 恒 false，已弃用。脚本每 500ms 上报 `raf`（前台≈30，后台/旧脚本 0 或 -1），
桥按 `(raf>=8, raf, seen)` 排序。`/status` 里 `stale_tabs` 按 `script_version` 比对 `sv` 列出跑旧脚本的标签。

## 自愈

桥死了跑 `bridge/restart.sh`（用 `readlink -f` 精确匹配，诱饵进程不会误杀）。
`xb` 的**读类命令**（`status`/`text`/`snapshot`）遇到连接失败（curl 退出码 7）会自己重启桥并重试一次，静默完成；
`js`/`click`/`fill` **绝不自动重试** —— 它们会改页面状态，重试等于又做一次。
桥会无声退出（日志最后一行还是正常回包）。**归因**：多半是用户在其他 App 里操作、系统回收了后台进程，
不是桥自己有 bug —— 2026-11-08 两次观察到这条，都发生在用户离开浏览器期间。自愈因此是必需的，不是锦上添花。
日志 `/tmp/bridge.log`，超 4 MiB 轮转。

## 截止与重投（3.9 起）

- 共享绝对 `deadline`（毫秒）：CLI 下发 → 桥投递前校验 → 页面执行前再校验（`deadline_exceeded`）。
- 迟到点击只补投 `type=="eval" && retry_safe && sent==1 && ack is None`；click/fill 永不重投。
- `op_id` 命中缓存返回原结果，同号改内容回 409。

## 安全边界（不许放宽）

任何 `Origin`（含 `Origin: null`）或 `Sec-Fetch-Site != none` → 403；非 JSON content-type（除 `/api/raw`）→ 403。
**永远不要给 8765 加 CORS 头**。漏洞是 Codex 实测出来的：普通网页曾能用 `text/plain` 跨站 POST 让受控标签执行 JS 并读回结果。

## 脚本安装的内幕

X 浏览器不读 `@updateURL`，⋮ 菜单也没有「检查更新」。覆盖安装（同 `@name`+`@namespace`）是原地升级，不产生重复条目。

全自动装（无障碍在跑时）：

```bash
android-open 'intent://127.0.0.1:8765/xb.user.js#Intent;scheme=http;package=com.mmbox.xbrowser;end'
# 屏幕出现「发现油猴脚本，是否安装？」→
android-a11y-cli ui find --text 安装        # 取 nodeId
android-a11y-cli tap node <nodeId>
# 验证：/status 里新导航的标签 sv 应等于 script_version
```
装完**当前标签仍是旧脚本**，必须导航/刷新才会加载新版本 —— 这就是 `stale_tabs` 存在的原因。

脚本靠 `GM_xmlhttpRequest` 打 127.0.0.1：跨域可用、混合内容不拦、往返 ~0.2s。
看门狗：40s 无成功轮询掐请求，60s 循环停摆换代重开。

## 标签为什么会堆、怎么不堆（2026-11-08 实测）

`android-open <url>` 每次都在 X 浏览器里**新开**一个标签，测试几十次就是几十个。
`window.close()` 实测**不生效也不报错**：给当前标签打标记 `document.title="CLOSEME2"` → 调用 → 2 秒后 `/status` 里那个标签还在（标记仍在）。所以不要指望用 JS 收尾。
正确做法是**默认不新开**：`xb open <url>` 先查 `/status -v` 有无标签，有就 `location.href` 导航它，没有才 `android-open`。
任务确实需要保留旧页（表单填一半、对照两页、登录流程中途）时用 `xb open --new`，这是唯一的合法新开入口。
注意多标签≠并行：只有前台标签能执行 JS，其余冻结（`raf=0`），`xb` 每次只投给可见标签。
真要清空已堆的标签：只有标签管理器「关闭全部」（无障碍坐标见 `mobile-ops/references/xbrowser.md`，或让用户手点一次）。

## 无障碍在什么位置

`android-a11y-cli` 只用于点浏览器自己的 UI（安装脚本、关标签、删脚本）。
Minis Integrations 有一道权限门，`service ping` 不走门容易误判成"服务正常"。
服务显示已开但仍 `SERVICE_NOT_RUNNING` 时：关 → 退到上一级 → 再进 → 开，才重新绑定。

## 协作

电脑端 Codex 通过挂载目录 `/var/minis/mounts/Download/协作/` 协作：`state.md` 是共识，`msg-NNN-{minis,codex}.md` 是往返信件，`src/vX.Y/` 是带 SHA256 的源码导出。
协作规则：不抢占手机前台、不改对方正在验收的文件、每版导出六份源码+指纹。

## 富文本填写为什么"只写一次"（v6.0 定稿理由）

三通道依次重试是**破坏性**的：真 Lexical 上填一次失败却在模型里叠出 4 份重复文本，因为每次尝试都真的改了状态。
现在的形状：同步派发一次 beforeinput → 用 `defaultPrevented` 判框架是否接管 → 没接管才在同一同步回合用 execCommand（普通 contenteditable 唯一可行的路）→ 之后所有 `settle()` 只读。
所以任何情况下最多写一次，也无需把 job deadline 传进 JS。`settle()` 一律带 `setTimeout` 硬上限：这个页面脚本在轮询主循环里 `await` 任务，rAF 在后台不触发会把整个标签挂死 60 秒。

## 内核上限（实测，别再重复发现）

X 浏览器内核 = Chrome 76–87。UA 是伪装的 iOS 串，`navigator.userAgentData` 为 null，别拿 UA 判版本；用特性探测。
真 Lexical 0.53 生产构建在这台机器上能跑，前提是 `esbuild --target=es2017` 重打包（`@lexical/*` 全家桶 + `@preact/signals-core`，apk 无 npm，用 registry tarball 铺 node_modules）。验收语料 `/var/minis/shared/phone-browser-test/`。

## 已知但暂未做的一处脆弱点

富文本分支靠属性级 `matches('[contenteditable="true"]')` 兜底，才不会发生"选中编辑器内子节点却清空整个编辑器"。`f.isContentEditable` 是继承属性，这层依赖关系很脆——更稳的写法是 `f.closest('[contenteditable]') === f` 显式断言。改动需要重跑富文本验收：`/var/minis/shared/phone-browser-test/fill-accept.sh`（4 组 17 个 `xb` 调用：严格模型编辑器 5 次填、普通 contenteditable 2 次、普通控件 5 次、回读 1 次）。
**它只打印结果、不自动判定**，得人对照看；跑一次要占用户屏幕 1 分钟左右。所以这条分支现在是"能不碰就不碰"。

`document.execCommand` 的布尔返回值没有进诊断（判定完全靠读回，所以不影响结论，只影响诊断信息量）。

## 裁剪纪律（2026-11-06）

范围只有四件事：**打开 / 读取 / 点击 / 填普通表单**。动手前先问：这个改动让那四件更快或更稳吗？不相关就别改。

已明确删除、**不要再加回来**：
- MCP 层（`mcp_edge.py` + `/cmd` 路由）：`xb` 已覆盖全部能力，而且它每次多花 2 秒。
- 滚动子系统（`SCROLL_JS` + `/api/scroll` + `xb scroll`）：快照改成收录全页元素后，滚动不再是读/点的前提。
- 富文本编辑器（Lexical/Slate/ProseMirror）的多通道填写：现只保留「试一次 → 等两帧 → 读回，不一致就拒绝」。
- 文件上传（`UPLOAD_JS` / `/api/upload` / `edge_upload` / `xb upload`）。
- Edge + 篡改猴整套（`minis.user.js`、`/minis.user.js` 路由、旧 `edge` CLI）。
- 把命令再包一层 JSON 的「结构化字段」入口：`xb` 位置参数已经够短（`xb fill '#a' 'x'` 17 字符），包一层反而多 50 字符 + 2 秒。

## 输出体积纪律（2026-11-08）

AI 每次任务读进上下文的就是 `xb` 的 stdout。实测同一页（MineBBS 190 个可交互元素）：
原始信封 17.8K → 紧凑 5.9K。所以：

- **默认不打印 `sel`**（每条 ~100 字符的全长 CSS 路径，点击根本用不到，只用 ref）和 `text`（要和 `xb text` 重复算两遍）。
- ref 打印时省掉固定前缀 `minis-ref:`，`xb click` 自动补回（省 11 字符/条）。
- 值类型回包（`js`）只回值本身；错误只留第一行（页面会回 200 字符的 JS 栈）。
- 新增输出必须能被 `--raw` 绕过，方便排障。

改 `xbops.py` 的常量后跑一次 `python3 -c "import sys;sys.path.insert(0,'bridge');import xbops"`，确认没有引用残留（曾因漏改 import 让 MCP 启动即崩，半天才发现）。
