# MiMo RL · Mission Control

小米 MiMo 大模型 RL 训练监控看板：双 run 态势、数据配比、逐数据源训练明细、actor/critic 指标、规则引擎自动分析、分析时间线。

**数据每 30 分钟自动刷新**（GitHub Actions → `data.js` → GitHub Pages）。

## 结构

| 文件 | 说明 |
|---|---|
| `index.html` | 看板页面（纯静态，无构建） |
| `data.js` | 由 `fetch_data.py` 生成的数据快照（勿手改） |
| `fetch_data.py` | 采集器：拉取 mimo.xiaomi.com/rl 的 status / live / series / notices / benchmarks |
| `.github/workflows/refresh.yml` | 每 30 分钟定时刷新并提交 |

## 手动刷新

```bash
python fetch_data.py
```

## 注意

- 数据源接口若变更（路径或字段），需同步修改 `fetch_data.py`
- 分析时间线在 `fetch_data.py` 的 `TIMELINE` 常量中维护
