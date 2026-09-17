# -*- coding: utf-8 -*-
"""
MiMo RL Mission Control · 数据采集器
每 30 分钟由 GitHub Actions 或本地定时任务运行，重新生成 data.js。

数据源：https://mimo.xiaomi.com/rl/api/{status,live,notices,benchmarks,runs,series}
"""
import json, sys, time, datetime, urllib.request, urllib.parse

BASE = "https://mimo.xiaomi.com/rl/api/"
RUNS = ("pro", "flash")

# 聚合指标（与官方看板 pins 一致）
PINS = ["dynsam/avg@n", "critic/rewards/mean", "actor/entropy_loss", "actor/pg_loss",
        "actor/grad_norm", "train_infer_diff/new_infer/kl", "ctx_total_length/mean",
        "dynsam/agg_turn/mean", "perf/total_num_tokens", "timing_s/step",
        "timing_s/outer_gen", "timing_s/trainer_ops", "dynsam/passrate/zero",
        "dynsam/passrate/one", "dynsam/infra_error/seq_rate", "env/active",
        "partial/avg_staleness", "dynsam/num_measurable"]

# 每个数据源的明细指标
SRC_METRICS = ["critic/{cat}/{ds}/rewards/mean", "critic/{cat}/{ds}/score/mean",
               "actor/{cat}/{ds}/entropy_loss", "actor/{cat}/{ds}/pg_loss",
               "actor/{cat}/{ds}/ppo_kl", "ctx_total_length/{cat}/{ds}/mean",
               "dynsam/{cat}/{ds}/num_accepted/step"]

CATEGORIES = ("code", "general", "cyber", "visual", "chat")

# 分析时间线（人工维护）
TIMELINE = [
    {"time": "2026-09-17 15:52", "title": "首次整体诊断",
     "points": ["双 run 健康区间：KL/熵/infra 错误率安全", "pro 因节点 VRAM 重启（短期扰动）",
                "flash 斜率更好：dynsam +0.070 vs pro +0.026，成本仅 1/3.5", "发现采样器失衡苗头：yfch 超采、cyber 慢判定"]},
    {"time": "2026-09-17 15:57", "title": "深度复盘（修正缓存快照，数据实际前进 4 步）",
     "points": ["数据集侧：code 67.7% 集中、yfch 5.8× 超采、cyber 单源瓶颈", "actor：pro 探索中收敛 vs flash 进入收敛期（KL +50% 需盯）",
                "critic：flash 校准良好 +0.015，pro 停滞与 actor 背离", "DeepSWE 更新：pro 62.24 → 65.78"]},
    {"time": "2026-09-17 16:34", "title": "接入逐数据源明细（api/series 按源指标）",
     "points": ["发现 pro 的 chat 类集体退化（lm3t -14%、8kb6 -7%），flash 同源 eup7 +25%", "cyber-9aui：flash reward +42% 全源最陡，却卡在 22/65 欠采",
                "yfch 双重代价：超采 5.8× 且 ctx 514k 全源最高", "code 类内部分化：m1dt 双 run +17~20% vs 尾部源回落"]},
    {"time": "2026-09-17 17:03", "title": "自动化分享看板上线",
     "points": ["30 分钟自动刷新，群链接即可预览", "规则引擎自动输出分析，时间线持续累积"]},
]


def get(path, **params):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "mimo-rl-mc/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def series(run, tags, version=None):
    out = {}
    for i in range(0, len(tags), 40):
        chunk = tags[i:i + 40]
        p = {"run": run, "tags": ",".join(chunk)}
        if version:
            p["v"] = version
        d = get("series", **p)
        version = d.get("version", version)
        for t, v in (d.get("series") or {}).items():
            if v:
                out[t] = v
        time.sleep(0.2)
    return out, version


def rnd(v, n=4):
    return round(v, n) if isinstance(v, float) else v


def fmt_num(v):
    if v is None:
        return None
    if abs(v) >= 1e9:
        return f"{v/1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"{v/1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"{v/1e3:.1f}k"
    return f"{v:g}"


def mean(xs):
    return sum(xs) / len(xs) if xs else 0


def main():
    data = {"generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "mimo.xiaomi.com/rl", "runs": {}, "metrics": [], "comp": [],
            "benchmarks": [], "notices": [], "timeline": TIMELINE}

    # --- notices & benchmarks ---
    try:
        now = time.time()
        ns = []
        for n in get("notices").get("notices", [])[:6]:
            ago = ""
            if n.get("t"):
                m = int((now - n["t"]) // 60)
                ago = f"{m//60}h {m%60}m ago" if m >= 60 else f"{m}m ago"
            ns.append({"ago": ago, "text": n.get("text", "")})
        data["notices"] = ns
    except Exception as e:
        print("notices fail:", e, file=sys.stderr)
    try:
        data["benchmarks"] = get("benchmarks").get("benchmarks", [])
        for b in data["benchmarks"]:
            hist = {}
            for run in RUNS:
                res = b.get("results", {}).get(run, {})
                steps = sorted(int(s) for s in res.keys())
                hist[run] = {"steps": steps, "vals": [rnd(res[str(s)], 2) for s in steps]}
            b["history"] = hist
    except Exception as e:
        print("benchmarks fail:", e, file=sys.stderr)

    # --- per run ---
    src_detail_all = {}
    for run in RUNS:
        st = get("status", run=run)
        lv = get("live", run=run)
        version = None
        agg, version = series(run, PINS, version)

        # 每源明细 tags：先发现有哪些源
        tags_all, _ = series(run, ["dynsam/code/dataset-yfch/num_accepted/step"], version)
        # 用 live feed 的源列表（25 个）构造明细 tags
        srcs = sorted(lv.get("latest", {}).get("ds", {}).keys())
        want = [tpl.format(cat=s.split("/")[0], ds=s.split("/")[1]) for s in srcs for tpl in SRC_METRICS]
        detail, _ = series(run, want, version)

        # run card
        step_info = st.get("step", {})
        totals = st.get("totals", {})
        run_start = st.get("run", {}).get("start")
        now = st.get("clock", {}).get("now", time.time())
        elapsed = ""
        if run_start:
            sec = now - run_start
            d, rem = divmod(int(sec), 86400)
            elapsed = f"{d}d {rem//3600:02d}:{(rem%3600)//60:02d}"
        dynsam = agg.get("dynsam/avg@n", [])
        latest_feed = lv.get("latest", {})
        data["runs"][run] = {
            "name": st.get("run", {}).get("label", f"mimo-v2.6-{run}"),
            "step": latest_feed.get("step") or step_info.get("last"),
            "phase": step_info.get("phase", ""),
            "progress": round(step_info.get("progress", 0) * 100),
            "gen_frac": round(step_info.get("gen_frac", 0) * 100),
            "elapsed": elapsed,
            "restarted_ago": step_info.get("since"),
            "dynsam": rnd(dynsam[-1], 3) if dynsam else None,
            "dynsam_d": rnd(dynsam[-1] - dynsam[0], 3) if len(dynsam) > 1 else None,
            "cost": f"${st.get('cost', {}).get('so_far', 0):,.0f}",
            "tok_step": fmt_num(totals.get("tokens_step")),
            "tok_total": fmt_num(totals.get("tokens_cum")),
            "samples": f"{int(totals.get('trained_cum', 0)/1000)}k",
            "batch": f"{int(totals.get('prompts_per_step', 1568)):,} prompts",
        }

        # 采样 feed（live latest 的每源 [accepted, target, in_flight, x]）
        feed = []
        for s in srcs:
            v = latest_feed.get("ds", {}).get(s) or []
            feed.append([s.split("/")[0], s.split("/")[1],
                         v[0] if len(v) > 0 else 0, v[1] if len(v) > 1 else 0,
                         v[2] if len(v) > 2 else 0])
        data["runs"][run]["feed"] = feed
        data["runs"][run]["feed_total"] = [latest_feed.get("accept"), latest_feed.get("target"),
                                           latest_feed.get("passrate"), latest_feed.get("judged")]
        src_detail_all[run] = {"steps": [], "sources": {s: {t: [rnd(x) for x in v] for t, v in detail.items()
                                                              if t.endswith(f"/{s}/rewards/mean") or f"/{s}/" in t}
                                                             for s in srcs}}
        time.sleep(0.3)

    # --- 聚合指标表（值 + 近窗 delta = 近3步均值 - 前3步均值） ---
    metrics_rows = []
    agg_all = {}
    for run in RUNS:
        a, _ = series(run, PINS)
        agg_all[run] = a
    for tag in PINS:
        row = [tag]
        for run in RUNS:
            vals = agg_all[run].get(tag)
            if not vals:
                row += [None, None, []]
                continue
            last = vals[-1]
            if len(vals) >= 6:
                d = mean(vals[-3:]) - mean(vals[-6:-3])
            elif len(vals) >= 2:
                d = vals[-1] - vals[0]
            else:
                d = 0
            row += [rnd(last, 4), rnd(d, 4), [rnd(x) for x in vals]]
        data["metrics"].append(row)

    # --- 配比（最近一步各源 num_accepted 按类汇总） ---
    comp = {c: 0 for c in CATEGORIES}
    for s, series_map in src_detail_all["pro"]["sources"].items():
        v = series_map.get(f"dynsam/{s}/num_accepted/step")
        if v:
            comp[s.split("/")[0]] += v[-1]
    tot = sum(comp.values()) or 1
    colors = {"code": "#22d3ee", "general": "#34d399", "cyber": "#e879f9",
              "visual": "#fbbf24", "chat": "#5f7099"}
    data["comp"] = [[c, round(comp[c] / tot * 100, 1), colors[c]] for c in CATEGORIES if comp[c] > 0]

    data["src_detail"] = src_detail_all

    out = "window.DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
    with open("data.js", "w", encoding="utf-8") as f:
        f.write(out)
    print("data.js written:", len(out), "bytes at", data["generated_at"])


if __name__ == "__main__":
    main()
