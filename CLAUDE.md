# CLAUDE.md — 强制输出规范

## 指标显示（每条回复第一行，不得省略）

格式：
```
[Metrics: $已用/$总余额 | Context: XX%]
```

规则：
- 初始余额：$3.97
- 已用金额：基于本次对话累计 Token 估算（claude-sonnet-4-6 定价：input $3/1M tokens，output $15/1M tokens）
- 总余额：$3.97（固定显示，不自动更新，用户手动告知时更新）
- Context 百分比：估算当前对话消耗的上下文窗口占比（参考 200K context window）

示例：
```
[Metrics: $0.18/$3.97 | Context: 12%]
```
