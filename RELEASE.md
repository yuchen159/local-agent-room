# 公开仓库打包说明

打包时间：2026-10-31
来源：本机运行版的暂存版 + 发布版专属改动

## 包含（34 个文件，约 2.3 MB）

- 服务端：`server.py`、`agents.py`、`approvals.py`、`media.py`、`battery.py`、`memory_notes.py`
- 小工具：`request_add.py`、`benchmark.py`、`verify_bound_access.py`、`room-harness-access.mjs`
- 前端：`dist/index.html`、`dist/app.js`、`dist/avatars/`
- 启动：`start.ps1`、`打开聊天室.cmd`
- 测试：`test_*.py`、`test_ui.js`、`test_harness_access.mjs`、`tools/test_watchdog.py`
- 看门狗：`tools/room_watchdog.py`
- 文档：`README.md`、`KNOWN_ISSUES.md`
- 许可证：`LICENSE`（MIT，署名 yuchen159）

## 明确排除

| 排除项 | 原因 |
| --- | --- |
| `data/` 整个目录 | 聊天数据库、附件、日志、备份、PID |
| `room-access.json` | 本机运行态 |
| `__pycache__/` | 编译缓存 |
| 各 `*.png` 验收截图 | 含本机界面与本机路径信息 |
| `验收记录.md`、`延迟与双入口验证*.md` | 本机验收记录，含机器细节 |

## 本版包含的行为

- 房间名可编辑：新库默认显示"给这里取个名字吧"，点左上角改名；名字只存本机 `meta`，不进提示词、不进导出；旧库升级保留原名。
- 每轮人类发言后的第一条 Agent 回复不折叠。
- 看板两栏固定显示，"需要你处理"为空时写"暂无事项"。
- **回答上限**：默认 40 次，设置里可改（2–1000）；达到后暂停，调高或点"继续"可接着聊。
  这与本机运行版不同——本机那台保持无上限，发布版才带 40 次默认。

## 已知需要你确认的事

1. **开源许可证**：目前没有 LICENSE。要开源得选一个（MIT / Apache-2.0 / AGPL 等），这一步需要你定。
2. `KNOWN_ISSUES.md` 里记的 3 条过期测试（插话/steering）要在公开前处理：要么改测试，要么在文档里说明。
3. 前端头像 `dist/avatars/*.png` 的来源与授权要确认后再公开。
4. 上传时把压缩包解开后提交目录内容，`_release_room.zip` 本身不必放进仓库。

## 验证

- `python -m unittest test_room`：39 项、38 通过；唯一失败是已知的过期插话测试。
- `node --check dist/app.js` 通过；`node test_ui.js` 通过。
- 发布包内敏感扫描：无本机路径、用户名、账号 ID、Cookie；无 `data/`、无 `__pycache__`。

## 怎么跑起来

- Python 3.11+，标准库；`python server.py` 默认监听 `127.0.0.1:8765`。
- 两位 Agent 分别需要本机已登录的 Harness / Codex CLI；没有它们时聊天室能开但不会有人回答。
