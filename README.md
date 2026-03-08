# my_agent_universe

基于 Gemini 的多 Agent 协作系统，支持联网搜索与智能分析。

```
my_agent_universe/
├── main.py              # 入口，单轮对话循环
├── agents/
│   ├── orchestrator.py  # 调度主控
│   ├── search_agent.py  # 搜索 Agent
│   └── analysis_agent.py# 分析 Agent
├── Tools/
│   ├── web_search.py    # SerpAPI 联网搜索
│   ├── text_extract.py  # 文本提取
│   └── summarizer.py    # 摘要生成
├── config/settings.py   # 全局配置
├── memory/context_store.py # 上下文存储
├── logs/                # 运行日志
└── .env                 # API Keys
```

## 环境变量

```
GEMINI_API_KEY=
SERPAPI_KEY=
```
