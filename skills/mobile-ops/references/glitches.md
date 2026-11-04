# 已知坑

只在排查失败或写新脚本时加载。日常操作不需要。

- **`input key back` 会连带退出当前 app**（面板/键盘不拦截时）。收面板用上滑，只有明确退页面才用 back。
- **`ui dump` 不返回 packageName**，要另调 `ui info`（+40 ms）。
- **`nodeId` 是快照序号**，界面重绘即失效。只能缓存"选择器"（文本/描述），不能缓存 id。
- **dump 别直接打进上下文**：5 KB 一次会挤爆。脚本里解析，只打印结论。
- **点完「截屏」1.1 s 内别再点**：面板还挂着，第二下会打到别的磁贴（会误开"多屏截图"）。
- **抢跑失败是静默的**：没报错也没图。所以 mshot 内部重试一次。

## 补充

- **用户正在操作时不要抢屏**：连点、切 app、弹键盘都会打断他。见 SKILL.md 顶部「用户在用时停下来」。
- **写死坐标必失效**：截屏磁贴实测从 (538,363) 被拖到 (916,363)，只隔几分钟。
  能用 `tap node` 就别用 `tap xy`。
- **`ui info` 的 packageName 不可靠**：荣耀实测在桌面时返回 `com.tencent.mobileqq`（残留窗口）。
  判前台看 `ui dump` 里节点 `packageName` 的众数，别只看 `ui info`。
  另外 `android-open 'intent:#Intent;package=com.openminis.app;end'` **在本机拉不回 Minis**，
  要从桌面图标点（第 2 屏 (668,612)）或通知。
- **报 `SERVICE_NOT_RUNNING` 而设置里开关是「已开启」**（荣耀/鸿蒙常见，已报 OpenMinis#519）：
  只是把开关点一遍没用，必须 **关 → 退回上一级 → 再进来 → 开**，才会重新绑定。
  恢复后 `service status` 立刻 `running:true`，不需要重启。
- **切换 app 优先用 `android-open 'intent:#Intent;package=<pkg>;end'`**（QQ 邮箱、Edge 实测可用），
  比 recents 稳。非用 recents 不可时，先 `uil` 看一眼顺序再点——卡片位置会随使用顺序变化，
  底部还紧挨着「固定屏幕」「关闭全部」这类系统动作。屏幕被固定时 HOME/recents 失效，长按 BACK 再 BACK 退出。
