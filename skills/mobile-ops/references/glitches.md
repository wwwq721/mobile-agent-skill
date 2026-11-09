# 已知坑与排查

只在排查失败或写新脚本时加载。日常操作不需要。

## 取屏失败（mshot）

症状：`取屏失败：通知栏没打开，或磁贴不在第一屏`

按顺序查：

1. **节点数是 0 吗**——`mshot` 会直接报「读不到任何界面节点，无障碍/授权没开」。
   这是最先要修的一步，不修后面全白跑。
2. **「截屏」磁贴位置变了吗**——`mshot` 直接点固定坐标 `(TILE_X, TILE_Y)`。
   报「点了 (x,y) 但没出图」就是磁贴被拖走了：dump 一次找 text/desc 含「截屏」
   的可点节点，把它 center 写回 `mshot.py` 顶部的两个常量。
3. **屏幕熄了吗**——熄屏时无障碍读不到节点，点磁贴也不会出图。
   无障碍发不了唤醒键（WAKEUP/POWER 都不支持），只能人来亮屏。
   遇到「点了两次都没出图」先看屏幕是不是黑的，别急着改坐标。

4. **上次的截图编辑层残留吗**——华为/荣耀截完会唤起 `HwMultiScreenShot`，
   它会挡住通知栏。脚本开头会检测并按一次 back 退掉。

**别指望更快**：1.95 秒里 1210ms 是系统截图管线（合成/编码/写盘/入相册），
是 Android 自己干的活，任何走通知栏磁贴的方案都要吃这笔。
要更快只能走 Shizuku 的 `screencap`（≈0.5s），那是另一条路。

**落盘时间会漂**：实测 1.2–3 秒，相册越大越靠后。所以是"固定等 0.95s + 轮询"
而不是死等某个值——写死任一个数，要么变慢，要么周期性失败。

## mloc 错误码

错误 JSON 走 stdout，退出码 1。

| 码 | 何时 | 怎么办 |
|---|---|---|
| `missing_selector` | learn 没给 `--text/--desc/--contains` | 补参数 |
| `no_match` | learn 时当前屏没有匹配 | 先导航到目标屏 |
| `ambiguous` | 可点目标不唯一 | `--desc` 收紧；分不开就别记 |
| `no_locator` | **当前前台 app** 没学过这名字 | 确认 app 在前台；没学过才 learn |
| `stale` | 学过但这屏没有 | 导航到那屏再试，**别急着重学**（会得 no_match） |
| `not_clickable` | 匹配到但不可点 | `--desc` 指向可点父控件 |
| `unknown_package` | 定不出所属 app | **若 dump 无节点 → 查无障碍/授权**，不是库坏了 |
| `unknown_target_package` | 目标节点无包名且查不到 | 不点，回 dump |
| `wrong_app` | 目标是别的 app | 拒绝点击，回 dump |

`tap` 的 `ok:false` 里若带 `STALE_NODE`，是节点在检查与点击之间失效了：重 dump 重定位一次。

## 三条能顶替多次往返的用法

`android-a11y-cli --help` 能列出全部组，这里只记**改变做法**的三条：

- `wait stable` —— 重绘后别 `sleep`，它实测 130ms 就能判定。同理 `wait appear --text X`。
- `dialog detect` —— 批量点击前先探一次，有弹窗就先关，避免后面几步全打在弹窗上。
- `tap id <resourceId>` —— 比文本稳，但多数 app 不给 id，别指望。

## 通用坑

- **`input key back` 会连带退出当前 app**（面板/键盘不拦截时）。只有明确要退页面才用 back。
- **`ui dump` 的节点不带 packageName**（本机实测 51/51 全无）。要包名只有两条路：
  `ui info`（顶层有，但会残留旧窗口）或 `ui node <id>`（单个节点，准确，+40ms）。
- **`nodeId` 是快照序号**，界面重绘即失效。只能缓存"选择器"（文本/描述），不能缓存 id。
- **dump 别直接打进上下文**：5 KB 一次会挤爆。脚本里解析，只打印结论。
- **点完「截屏」1.1 s 内别再点**：面板还挂着，第二下会打到别的磁贴（会误开"多屏截图"）。
- **写死坐标必失效**：截屏磁贴实测从 (538,363) 被拖到 (916,363)，只隔几分钟。
- **`ui find` 的 `--text` / `--desc` 是精确相等，不是包含**（源码 `AccessibilityOffloadHandler.matchesPredicate`）。
  要子串用 `--text-contains`。
- **`ui info` 的 packageName 会残留旧窗口**：荣耀实测在桌面时返回 `com.tencent.mobileqq`。
- **报 `SERVICE_NOT_RUNNING` 而设置里开关是「已开启」**（荣耀/鸿蒙常见，已报 OpenMinis#519）：
  关 → 退回上一级 → 再进来 → 开，才重新绑定。只点一次开关无效。
