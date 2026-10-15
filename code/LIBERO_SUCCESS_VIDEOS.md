# 十个 LIBERO-Plus Goal 任务的成功示例视频

2026-10-15 整理。以下每个源回合的 `episode/result.json` 均为 `success=true` 且 `program_finished=true`；未重新运行实验，未改变控制代码或模型输入。

视频使用原始 agentview 快照，按记录的 native tick、20 Hz 仿真时间拼接，省去模型等待。两个观测之间保持上一张快照，**不是连续逐帧录屏**。Goal1098 只有九个不重复时刻，跳帧尤其明显。Goal1202 同一回合前后包含 JPG/PNG，先无损统一图片格式后编码，完整保留开抽屉及放碗两个部分。

Goal1202 仅为开发回合成功示例，后续新初态失败，尚未稳定。其余九项有固定版本五个未见初态 5/5 的记录；这个小样本结果不代表整个 benchmark。

| Goal | 任务与视频 | 源回合 |
| ---: | --- | --- |
| 1098 | [开中层抽屉（阶段关键帧）](runs/2026-10-15-libero-ten-success-videos/goal1098.mp4) | `2026-10-14-5880-goal1098-init6-frozen-v19` |
| 1144 | [碗放炉面](runs/2026-10-15-libero-ten-success-videos/goal1144.mp4) | `2026-10-13-5880-goal1144-init5-frozen-v1` |
| 1163 | [酒瓶放柜顶](runs/2026-10-15-libero-ten-success-videos/goal1163.mp4) | `2026-10-13-5880-goal1163-init6-frozen-v1` |
| 1202 | [开抽屉放碗（尚未稳定）](runs/2026-10-15-libero-ten-success-videos/goal1202.mp4) | `2026-10-14-5880-goal1202-init3-visible-insertion-v43` |
| 1252 | [碗放柜顶](runs/2026-10-15-libero-ten-success-videos/goal1252.mp4) | `2026-10-13-5880-goal1252-init4-frozen-v1` |
| 1296 | [推盘到炉前](runs/2026-10-15-libero-ten-success-videos/goal1296.mp4) | `2026-10-14-5880-goal1296-init12-rim-slide-frozen-v18` |
| 1335 | [奶酪放碗](runs/2026-10-15-libero-ten-success-videos/goal1335.mp4) | `2026-10-13-5880-goal1335-frozen-v5-init23` |
| 1383 | [开炉灶旋钮](runs/2026-10-15-libero-ten-success-videos/goal1383.mp4) | `2026-10-14-5880-goal1383-init8-cpu-frozen` |
| 1423 | [碗放盘上](runs/2026-10-15-libero-ten-success-videos/goal1423.mp4) | `2026-10-13-5880-goal1423-frozen-v4-init10` |
| 1458 | [酒瓶入斜架](runs/2026-10-15-libero-ten-success-videos/goal1458.mp4) | `2026-10-12-5880-goal1458-init11-cpu-v2` |

[导出清单](runs/2026-10-15-libero-ten-success-videos/manifest.json) 保存各视频与原始结果的 SHA256、快照路径及 SHA256、native tick 范围、时长和源配置。每个视频另有 ffprobe 编码检查和导出的末帧 PNG。视频保存在本机及 5880-jump 的相同项目相对目录，二进制素材不加入 Git。
