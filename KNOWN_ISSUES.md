# 已知插话缺陷（2026-10-27）

本次图片功能回归明确保留以下原版缺陷，不把它们计作测试通过：

1. test_room.Tests.test_submitted_interjection_notifies_running_codex_without_exposing_old_draft：输入暂停后提交新消息，没有向运行中的Codex投递插话通知，预期的一次更新未发生。
2. test_room.Tests.test_failed_superseded_background_does_not_erase_new_message_queue：被新消息替代的旧后台生成若失败，异常分支会暂停并清空新消息队列。
3. test_steering.Steering.test_inflight_input_uses_matching_turn_and_handles_acknowledgement：Agent缺少queue_steer，运行中投递与确认测试报AttributeError。
4. test_steering.Steering.test_stale_update_cannot_reach_another_turn：Agent缺少steer_updates，过期插话隔离测试无法执行。

1、2已在头像更新时对未修改public/room复现；3、4在本次未修改public/room复现。它们涉及同一组尚未落地的插话支持。本次仅安装图片/表情和界面改名，不随附调度修复。
