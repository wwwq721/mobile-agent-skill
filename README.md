# 手机端 AI 操控技能包

在 Android 手机上让 AI 直接操作手机：读屏、点按钮、填表单、操作浏览器并保留登录态。
不是演示 Demo，是能替自己干杂事的工具链。

## 它由两个技能组成

| 技能 | 解决什么 | 关键手段 |
|---|---|---|
| `mobile-ops` | 操作任意 App 的原生界面 | Android 无障碍服务（AccessibilityService）：`ui dump` 拿节点树 → 按文本/坐标点击 → 输入 |
| `phone-browser` | 在浏览器里读写网页、保留登录态 | 油猴脚本 + 本地长轮询桥：沙箱里发命令，页面内执行 JS，把 DOM 结果送回 |

两者互补：原生界面拿不到 DOM 就用 `mobile-ops`，网页要精确取数就用 `phone-browser`。

## 实测环境

- Honor 手机 / Android 10（SDK 29）/ 1080×2400
- 运行宿主：Minis（提供 `android-a11y-cli`、`android-clipboard`、`minis-scheduled` 等命令行工具）
- 浏览器：X 浏览器（`com.mmbox.xbrowser`）+ 用户脚本
- 坐标参数都是这台机器量出来的，换机型要重新 `ui dump` 校准

## 装起来

```bash
sh install.sh      # 查依赖 → 装 xb/mshot/mloc → 起桥 → 自检
```

手动步骤、验收命令、排错表在 [INSTALL.md](INSTALL.md)。装完还要人工做两件事：
**在手机浏览器里装用户脚本**（`http://127.0.0.1:8765/xb.user.js`，装前已开的标签要刷新）、
**开无障碍服务**（只有原生操控那一半需要）。

> 浏览器这一半靠的就是那个用户脚本（`skills/phone-browser/xb/minis-xb.user.js`，桥自动对外提供 `/xb.user.js`）——
> 没有它，`xb` 只会返回"没有标签"。

## 跑起来之后

```bash
xb open 'https://example.com/'   # 复用现有标签
xb snapshot                      # 可点元素的紧凑列表
xb click 'ref 或 CSS'
xb text                          # 正文前 3000 字
```

- "打开 QQ 邮箱，给 xxx 写一封信，收件人/主题/正文按我说的填，写完先别发"
- "在浏览器里查一下某平台的公告，把所有带日期的条目列出来"
- "把当前屏幕上的按钮读一遍，告诉我哪个能提交"

## 三个最值得抄的经验

1. **一次 dump 拿全量结构，然后一条命令连续执行。** 点击 50 ms，模型往返 2–8 s，慢的从来不是点，是"看一眼再点"。
2. **浏览器只有最可见的那个标签能执行 JS。** 后台标签会被冻结，命令必然超时；要连续操作就把"打开→做→取"压进同一条命令。
3. **富文本框不吃外部写入。** 原生界面走"写剪贴板 → 长按 → 粘贴"；网页里的 Lexical/Slate 直接如实失败，别重试。

## 已知边界

- 仅 Android ≤ 10 需要截图绕路（`mshot` 走通知栏截屏磁贴）；Android 11+ 直接用 `ui screenshot`。
- 无障碍服务被系统强停后需要重新授权。
- 同一块屏幕不要同时让人和 AI 操作：人在用时应当停手。

## 许可

木兰宽松许可证第 2 版（Mulan PSL-2.0），与 EduWork 的贡献许可一致。
脚本与文档均为原创；`bridge.py` / `minis-xb.user.js` 不含第三方代码。
