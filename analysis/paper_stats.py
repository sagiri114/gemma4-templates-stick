#!/usr/bin/env python3
"""论文赛写作数据：直接从主赛结果包和 A0 归档重算 Writeup 用到的数字，并画两张图。

不解压，用 zipfile / tarfile 读成员，磁盘紧张的机器也能跑。统计部分只用标准库；
功效模拟需要 numpy，画图需要 matplotlib（缺了就跳过对应部分并在汇总里写明）。

用法：
    python paper_stats.py --results "<主赛/02_本地评测/结果>" \
        --a0 "<论文赛/A0结果_20261020/formal_a0_full_20261020.tgz>" --out out --figures

输出（--out 目录）：
    summary.md            人读汇总，每节写明口径
    stats.json            全部数字
    runs.csv              每次运行一行
    comparisons.csv       每个配对比较一行，带报告值和核对结果
    fig1_intervals.csv/png  图 1 数据与图
    fig2_poison.csv/png     图 2 数据与图

口径与 主赛/02_本地评测/scripts/summarize.py 一致：只统计 status=ok；每题先对各遍取平均，
再按题配对 bootstrap（random.Random(0)，5000 次，取排序后第 125、4875 个值）。
第七轮报告用的是线性分位数，两种都算，核对时任一种与报告一致即通过。
"""
from __future__ import annotations

import argparse
import collections
import csv

import json
import math
import os
import random
import re
import statistics
import sys
import tarfile
import zipfile

MISS = 'mandatory input parameters are not present'
SWALLOW = re.compile(r'[`"]\s*,\s*old_string\s*:')

# ---------------------------------------------------------------- 配置登记
# key, 结果包, 包内运行目录, 类型, 图上用的英文名
CONFIGS = [
    ('base', 'base_v1_20261029_full_20261029.zip', ['base_v1_20261029'], 'full', 'Base (Budget-Fit)'),
    ('C01b_r2', 'round2_queue_20261030_full.zip', ['runs/r2_C01b_v1'], 'full', 'C01b (round 2)'),
    ('C03b', 'round2_queue_20261030_full.zip', ['runs/r2_C03b_v1'], 'full', 'C03b: + check skill'),
    ('C04', 'round2_queue_20261030_full.zip', ['runs/r2_C04_v1'], 'full', 'C04: temperature 0.7'),
    ('C01b_r4', 'round4_20261031_full.zip', ['runs/r4_C01b'], 'full', 'C01b (round 4)'),
    ('T2048', 'round4_20261031_full.zip', ['runs/r4_T2048'], 'full', 'T2048: thinking cap 2048'),
    ('T3072', 'round4_20261031_full.zip', ['runs/r4_T3072'], 'full', 'T3072: thinking cap 3072'),
    ('X', 'round4_20261031_full.zip', ['runs/r4_X'], 'full', 'X: read/search rules'),
    ('C01b_r7', 'round7_K3_fail500_20261101.zip',
     [f'runs/r7_K3_fC_C01b_{s}' for s in ('A0', 'A1', 'B0', 'B1')], 'full', 'C01b (round 7)'),
    ('B30', 'round7_K3_fail500_20261101.zip',
     [f'runs/r7_K3_fC_B30_{s}' for s in ('A0', 'A1', 'B0', 'B1')], 'full', 'B30: call cap 30'),
    # 小门禁（题目按风险挑选，不并入分辨率结论）
    ('g1_base', 'c01_vs_base_20261029_dev12_full.zip', ['runs/baseline_r0', 'runs/baseline_r1'], 'gate', 'Base'),
    ('g1_C01', 'c01_vs_base_20261029_dev12_full.zip', ['runs/C01_r0', 'runs/C01_r1'], 'gate', 'C01'),
    ('g1r_base', 'r01_vs_base_20261029_v2_main_dev12_full.zip', ['runs/baseline_r0', 'runs/baseline_r1'], 'gate', 'Base'),
    ('g1r_R01', 'r01_vs_base_20261029_v2_main_dev12_full.zip', ['runs/R01_r0', 'runs/R01_r1'], 'gate', 'R01'),
    ('r3_C01b', 'round3_stage1_20261031_full.zip', ['runs/r3_C01b_s1'], 'gate', 'C01b'),
    ('r3_C01c', 'round3_stage1_20261031_full.zip', ['runs/r3_C01c_s1'], 'gate', 'C01c'),
    ('g5_C01b', 'round5_gate1_20261101.zip', ['runs/r5_g1_C01b_A', 'runs/r5_g1_C01b_B'], 'gate', 'C01b'),
    ('g5_V', 'round5_gate1_20261101.zip', ['runs/r5_g1_V_A', 'runs/r5_g1_V_B'], 'gate', 'V'),
    ('g6_C01b', 'round6_gateB_20261101.zip', ['runs/r6_gB_C01b_A', 'runs/r6_gB_C01b_B'], 'gate', 'C01b'),
    ('g6_E', 'round6_gateB_20261101.zip', ['runs/r6_gB_E_A', 'runs/r6_gB_E_B'], 'gate', 'E'),
    ('g7_C01b_K2', 'round7_K2_gateB_20261101.zip', ['runs/r7_K2_gB_C01b_A', 'runs/r7_K2_gB_C01b_B'], 'gate', 'C01b'),
    ('g7_K2', 'round7_K2_gateB_20261101.zip', ['runs/r7_K2_gB_K2_A', 'runs/r7_K2_gB_K2_B'], 'gate', 'K2'),
    ('g7_C01b_K3', 'round7_K3_gateB_20261101.zip', ['runs/r7_K3_gB_C01b_A', 'runs/r7_K3_gB_C01b_B'], 'gate', 'C01b'),
    ('g7_K3', 'round7_K3_gateB_20261101.zip', ['runs/r7_K3_gB_K3_A', 'runs/r7_K3_gB_K3_B'], 'gate', 'K3'),
]
FULL = [c[0] for c in CONFIGS if c[3] == 'full']
C01B_RUNS = ['C01b_r2', 'C01b_r4', 'C01b_r7']
LABEL = {c[0]: c[4] for c in CONFIGS}

# 配对比较：(对照, 候选, 类型)。类型 candidate=候选对同场或历史对照；rerun=同一配置重跑。
COMPARISONS = [
    ('base', 'C01b_r2', 'candidate'), ('base', 'C03b', 'candidate'), ('base', 'C04', 'candidate'),
    ('C01b_r2', 'C03b', 'candidate'),
    ('C01b_r4', 'T2048', 'candidate'), ('C01b_r4', 'T3072', 'candidate'), ('C01b_r4', 'X', 'candidate'),
    ('C01b_r7', 'B30', 'candidate'),
    ('C01b_r2', 'C01b_r4', 'rerun'), ('C01b_r2', 'C01b_r7', 'rerun'), ('C01b_r4', 'C01b_r7', 'rerun'),
    ('g1_base', 'g1_C01', 'gate'), ('g1r_base', 'g1r_R01', 'gate'), ('r3_C01b', 'r3_C01c', 'gate'),
    ('g5_C01b', 'g5_V', 'gate'), ('g6_C01b', 'g6_E', 'gate'),
    ('g7_C01b_K2', 'g7_K2', 'gate'), ('g7_C01b_K3', 'g7_K3', 'gate'),
]
# 各轮报告里的数字（差值、区间下端、上端，单位：百分点），用来核对本脚本。
REPORTED = {
    ('base', 'C04'): (2.0, -3.6, 7.6, '第二轮 完整对比报告.md'),
    ('base', 'C01b_r2'): (2.4, -2.0, 6.8, '第二轮 完整对比报告.md'),
    ('base', 'C03b'): (2.8, -1.6, 7.6, '第二轮 完整对比报告.md'),
    ('C01b_r2', 'C03b'): (0.4, -3.6, 4.4, '第二轮 完整对比报告.md'),
    ('C01b_r2', 'C01b_r4'): (-2.4, -6.8, 2.0, '第四轮 对比报告.md'),
    ('C01b_r4', 'T2048'): (0.0, -4.0, 4.0, '第四轮 对比报告.md'),
    ('C01b_r4', 'T3072'): (0.8, -3.2, 5.2, '第四轮 对比报告.md'),
    ('C01b_r4', 'X'): (2.8, -1.6, 7.2, '第四轮 对比报告.md'),
    ('C01b_r7', 'B30'): (2.4, -2.8, 7.2, '第七轮 K3_B30全量对比报告.md'),
    ('C01b_r2', 'C01b_r7'): (-2.4, -6.4, 1.6, '第七轮 K3_B30全量对比报告.md'),
    ('C01b_r4', 'C01b_r7'): (0.0, -4.0, 3.6, '第七轮 K3_B30全量对比报告.md'),
    ('r3_C01b', 'r3_C01c'): (-2.5, -11.2, 5.0, '第三轮 第一阶段对比报告.md'),
    ('g7_C01b_K3', 'g7_K3'): (-12.5, -25.0, 0.0, '第七轮 K3执行证据/门B/分析/paired_quality.md'),
    ('base@a0', 'base@a1'): (4.0, -3.2, 11.2, '第二轮 summary_recomputed.md'),
    ('C04@a0', 'C04@a1'): (1.6, -2.4, 6.4, '第二轮 summary_recomputed.md'),
    ('C01b_r2@a0', 'C01b_r2@a1'): (2.4, -2.4, 7.2, '第二轮 summary_recomputed.md'),
    ('C03b@a0', 'C03b@a1'): (3.2, -2.4, 8.8, '第二轮 summary_recomputed.md'),
    ('C01b_r4@a0', 'C01b_r4@a1'): (-2.4, -8.0, 3.2, '第四轮 paired_candidates.md'),
    ('T2048@a0', 'T2048@a1'): (0.8, -4.8, 6.4, '第四轮 paired_candidates.md'),
    ('T3072@a0', 'T3072@a1'): (2.4, -3.2, 8.0, '第四轮 paired_candidates.md'),
    ('X@a0', 'X@a1'): (1.6, -5.6, 8.8, '第四轮 paired_candidates.md'),
}


# ---------------------------------------------------------------- 读取
RUN_RE = re.compile(r'^(?P<run>(?:[^/]+/)*?[^/]+)/tasks/(?P<task>[^/]+)/(?P<att>a\d+)/(?P<rest>.+)$')


def index_zip(zf):
    """run 目录 -> {(task, att): {'result': 成员名, 'traces': [成员名]}}"""
    idx = collections.defaultdict(dict)
    for name in zf.namelist():
        m = RUN_RE.match(name)
        if not m:
            continue
        slot = idx[m['run']].setdefault((m['task'], m['att']), {'result': None, 'traces': []})
        if m['rest'] == 'result.json':
            slot['result'] = name
        elif m['rest'].startswith('official/traces/') and m['rest'].endswith('.json'):
            slot['traces'].append(name)
    return idx


def parse_calls(trace):
    calls = []
    for s in trace.get('steps', []):
        if s.get('source') != 'agent':
            continue
        obs = (s.get('observation') or {}).get('content') or ''
        try:
            payload = json.loads(obs)
        except (ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        err = str(payload.get('error') or '')
        failed = bool(err) or payload.get('status') == 'error'
        missing = []
        if MISS in err:
            seg = err.split('present:', 1)[-1].split('You could retry', 1)[0]
            missing = re.findall(r'[a-z_]+', seg)
        for tc in s.get('tool_calls') or []:
            args = tc.get('arguments') or {}
            calls.append(dict(name=tc.get('function_name'), args=args, missing=missing, failed=failed,
                              err=err[:200],
                              sig=(tc.get('function_name') or '') + json.dumps(args, sort_keys=True,
                                                                              ensure_ascii=False)))
    return calls


def run_metrics(calls):
    """一次运行的工具调用指标。中毒 = 本次运行里第一次 edit_file 缺必填参数。"""
    m = collections.Counter()
    poisoned = False
    chain = best = 0
    for i, c in enumerate(calls):
        if c['missing']:
            m['missing_calls'] += 1
            chain += 1
            best = max(best, chain)
        else:
            chain = 0
        prev = calls[i - 1] if i else None
        if prev and prev['failed'] and c['sig'] == prev['sig'] and c['err'] == prev['err']:
            m['identical_failed_resend'] += 1
        if c['missing']:
            nxt = calls[i + 1] if i + 1 < len(calls) else None
            if nxt is not None and nxt['sig'] == c['sig']:
                m['resend_after_missing'] += 1
        if c['name'] != 'edit_file':
            continue
        miss = bool(c['missing'])
        if not poisoned:
            m['edit_pre_n'] += 1
            m['edit_pre_f'] += miss
            if miss:
                poisoned = True
        else:
            m['edit_post_n'] += 1
            m['edit_post_f'] += miss
    m['max_missing_chain'] = best
    m['poisoned'] = int(poisoned)
    m['calls_total'] = len(calls)
    return m


def load_config(results_dir, key, zname, dirs, cache):
    path = os.path.join(results_dir, zname)
    if path not in cache:
        zf = zipfile.ZipFile(path)
        cache[path] = (zf, index_zip(zf))
    zf, idx = cache[path]
    rows = []
    for d in dirs:
        if d not in idx:
            raise SystemExit(f'{zname} 里没有运行目录 {d}')
        for (task, att), slot in sorted(idx[d].items()):
            if slot['result'] is None:
                continue
            res = json.loads(zf.read(slot['result']))
            row = dict(config=key, run_dir=d, task=res.get('instance_id', task),
                       attempt=int(res.get('attempt', att[1:])), status=res.get('status'),
                       resolved=bool(res.get('resolved')), tool_calls=res.get('tool_calls'),
                       agent_seconds=res.get('agent_seconds'), hit_time_cap=bool(res.get('hit_time_cap')),
                       hit_call_cap=bool(res.get('hit_call_cap')), has_trace=bool(slot['traces']))
            if slot['traces']:
                m = run_metrics(parse_calls(json.loads(zf.read(sorted(slot['traces'])[0]))))
                row.update(m)
            rows.append(row)
    return rows


# ---------------------------------------------------------------- 统计
def per_task_rate(rows):
    d = collections.defaultdict(list)
    for r in rows:
        if r['status'] == 'ok':
            d[r['task']].append(r['resolved'])
    return {k: sum(v) / len(v) for k, v in d.items()}


def sign_test(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def linear_q(v, p):
    k = (len(v) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def paired(rows_a, rows_b, seed=0, n_boot=5000):
    """与 summarize.py 的 compare() 相同：每题重复成功率之差，按题配对 bootstrap。"""
    A, B = per_task_rate(rows_a), per_task_rate(rows_b)
    common = sorted(set(A) & set(B))
    n = len(common)
    diff = {i: B[i] - A[i] for i in common}
    md = sum(diff.values()) / n
    rng = random.Random(seed)
    boots = sorted(sum(diff[rng.choice(common)] for _ in common) / n for _ in range(n_boot))
    up = sum(1 for i in common if diff[i] > 0)
    down = sum(1 for i in common if diff[i] < 0)
    ok_a = [r for r in rows_a if r['status'] == 'ok' and r['task'] in diff]
    ok_b = [r for r in rows_b if r['status'] == 'ok' and r['task'] in diff]
    return dict(n_tasks=n, runs_a=len(ok_a), runs_b=len(ok_b),
                solved_a=sum(r['resolved'] for r in ok_a), solved_b=sum(r['resolved'] for r in ok_b),
                diff_pts=100 * md,
                ci_idx=(100 * boots[int(0.025 * n_boot) - 1], 100 * boots[int(0.975 * n_boot) - 1]),
                ci_lin=(100 * linear_q(boots, 0.025), 100 * linear_q(boots, 0.975)),
                up=up, down=down, same=n - up - down, sign_p=sign_test(up, down))


def check_reported(key, res):
    if key not in REPORTED:
        return None
    d, lo, hi, src = REPORTED[key]
    ok_d = abs(round(res['diff_pts'], 1) - d) < 0.051
    ok_idx = abs(round(res['ci_idx'][0], 1) - lo) < 0.051 and abs(round(res['ci_idx'][1], 1) - hi) < 0.051
    ok_lin = abs(round(res['ci_lin'][0], 1) - lo) < 0.051 and abs(round(res['ci_lin'][1], 1) - hi) < 0.051
    return dict(reported=(d, lo, hi), source=src, match=bool(ok_d and (ok_idx or ok_lin)),
                match_method='index' if ok_idx else ('linear' if ok_lin else 'none'))


def flips(rows_a, rows_b):
    a = {(r['task'], r['attempt']): r['resolved'] for r in rows_a if r['status'] == 'ok'}
    b = {(r['task'], r['attempt']): r['resolved'] for r in rows_b if r['status'] == 'ok'}
    common = sorted(set(a) & set(b))
    f = sum(a[k] != b[k] for k in common)
    return dict(n=len(common), flips=f, rate_pct=100 * f / len(common))


def success_counts(by_cfg, keys):
    cnt = collections.defaultdict(int)
    att = collections.defaultdict(int)
    for k in keys:
        for r in by_cfg[k]:
            if r['status'] == 'ok':
                cnt[r['task']] += r['resolved']
                att[r['task']] += 1
    return cnt, att


def solvability(by_cfg, keys):
    cnt, att = success_counts(by_cfg, keys)
    n_att = sorted(set(att.values()))
    tasks = sorted(cnt)
    full = max(att.values())
    never = [t for t in tasks if cnt[t] == 0]
    always = [t for t in tasks if cnt[t] == att[t]]
    mixed = [t for t in tasks if 0 < cnt[t] < att[t]]
    by_repo = collections.defaultdict(lambda: collections.Counter())
    for t in tasks:
        repo = t.split('_')[0]
        by_repo[repo]['tasks'] += 1
        by_repo[repo]['never'] += t in never
        by_repo[repo]['always'] += t in always
        by_repo[repo]['mixed'] += t in mixed
    dist = collections.Counter(cnt[t] for t in tasks)
    return dict(configs=keys, attempts_per_task=n_att, n_tasks=len(tasks), never=len(never),
                always=len(always), mixed=len(mixed), by_repo={k: dict(v) for k, v in sorted(by_repo.items())},
                distribution={int(k): v for k, v in sorted(dist.items())}, attempts_max=full)


def shift_for(p, target, np):
    """找平移量 s，使 mean(min(1, p + s)) - mean(p) 恰为 target（二分）。"""
    lo, hi = 0.0, 1.0
    if np.minimum(1.0, p + hi).mean() - p.mean() < target:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if np.minimum(1.0, p + mid).mean() - p.mean() < target:
            lo = mid
        else:
            hi = mid
    return hi


SHOW = (2, 3, 4, 5, 6, 7, 8)


def power_section(by_cfg, sims, comps, seed=0):
    try:
        import numpy as np
    except ImportError:
        return dict(skipped='numpy 不可用')
    out = {}
    estimators = {
        'c01b6': ('C01b 三次全量（每题 6 次）的经验成功率', C01B_RUNS),
        'pool20': ('10 个全量配置合并（每题 20 次）的经验成功率', FULL),
    }
    grid = [x / 2 for x in range(1, 25)]  # 真实平均差 0.5–12 个百分点
    for ek, (desc, keys) in estimators.items():
        cnt, att = success_counts(by_cfg, keys)
        tasks = sorted(cnt)
        p = np.array([cnt[t] / att[t] for t in tasks])
        n = len(p)
        sigma = math.sqrt(float(np.sum(p * (1 - p)))) / n  # 两个配置各 2 遍时，每题均值差的均值的标准差
        res = dict(description=desc, n_tasks=n, mean_rate_pct=float(100 * p.mean()),
                   sd_diff_two_runs_solves=100 * sigma * 2.5, sd_diff_two_runs_pts=100 * sigma,
                   normal_approx_mde80_pts=100 * sigma * (1.96 + 0.8416), by_repeats={})
        rng = np.random.default_rng(seed)
        for R in (2, 4, 8, 16):
            a0 = rng.binomial(R, p, size=(sims, n)).mean(axis=1) / R
            b0 = rng.binomial(R, p, size=(sims, n)).mean(axis=1) / R
            null = b0 - a0
            lo, hi = float(np.quantile(null, 0.025)), float(np.quantile(null, 0.975))
            powers = {}
            for d in grid:
                sh = shift_for(p, d / 100, np)
                pb = np.minimum(1.0, p + sh)
                a = rng.binomial(R, p, size=(sims, n)).mean(axis=1) / R
                b = rng.binomial(R, pb, size=(sims, n)).mean(axis=1) / R
                powers[d] = float(np.mean((b - a) > hi))
            mde80 = next((d for d in grid if powers[d] >= 0.8), None)
            res['by_repeats'][R] = dict(runs_per_config=R * n, null_95_pts=(100 * lo, 100 * hi),
                                        power={str(d): powers[float(d)] for d in SHOW}, mde80_pts=mde80)
        out[ek] = res
    half = [(c['ci_idx'][1] - c['ci_idx'][0]) / 2 for c in comps if c['kind'] in ('candidate', 'rerun')]
    out['observed_ci'] = dict(n=len(half), mean_half_width_pts=statistics.mean(half), min=min(half), max=max(half),
                              implied_mde80_pts=statistics.mean(half) * (1.96 + 0.8416) / 1.96)
    out['assumption'] = ('每题成功率取经验值；候选对每题加同一个平移量（超过 1 截到 1），平移量用二分法选到'
                         '“截断后的真实平均差”恰为表头的值；“检出”= 模拟差值超过零假设下差值分布的 97.5% 分位，'
                         '等价于双侧 95% 区间不含 0。observed_ci 用实际 11 个全量比较的 bootstrap 区间半宽，'
                         '按正态近似换算 80% 功效所需的差距。')
    return out


def poison_section(by_cfg, keys):
    table = {}
    tot = collections.Counter()
    for k in keys:
        rows = [r for r in by_cfg[k] if r['status'] == 'ok' and r['has_trace']]
        c = collections.Counter()
        for r in rows:
            for f in ('edit_pre_n', 'edit_pre_f', 'edit_post_n', 'edit_post_f', 'missing_calls',
                      'identical_failed_resend', 'resend_after_missing'):
                c[f] += r.get(f, 0)
            c['runs'] += 1
            c['poisoned'] += r.get('poisoned', 0)
            c['poisoned_solved'] += r.get('poisoned', 0) and r['resolved']
            c['clean_solved'] += (not r.get('poisoned', 0)) and r['resolved']
            c['max_missing_chain'] = max(c['max_missing_chain'], r.get('max_missing_chain', 0))
        for f in c:
            if f != 'max_missing_chain':
                tot[f] += c[f]
        tot['max_missing_chain'] = max(tot['max_missing_chain'], c['max_missing_chain'])
        table[k] = summarize_poison(c)
    return table, summarize_poison(tot)


def summarize_poison(c):
    d = dict(c)
    d['pre_rate_pct'] = 100 * c['edit_pre_f'] / c['edit_pre_n'] if c['edit_pre_n'] else None
    d['post_rate_pct'] = 100 * c['edit_post_f'] / c['edit_post_n'] if c['edit_post_n'] else None
    clean = c['runs'] - c['poisoned']
    d['poisoned_solve_pct'] = 100 * c['poisoned_solved'] / c['poisoned'] if c['poisoned'] else None
    d['clean_solve_pct'] = 100 * c['clean_solved'] / clean if clean else None
    return d


def within_task_poison(by_cfg, keys):
    """同一题内：中毒运行与未中毒运行的解出率。只用同时有两种运行的题，先按题平均再跨题平均。
    上界：把这些题里每次中毒运行的结果换成该题未中毒运行的解出率，总解出数能多多少（观察关联，不是因果）。"""
    rows = [r for k in keys for r in by_cfg[k] if r['status'] == 'ok' and r['has_trace']]
    by_task = collections.defaultdict(lambda: {'p': [], 'c': []})
    for r in rows:
        by_task[r['task']]['p' if r.get('poisoned') else 'c'].append(r['resolved'])
    both = {t: v for t, v in by_task.items() if v['p'] and v['c']}
    if not both:
        return dict(n_tasks=0)
    pr = statistics.mean(sum(v['p']) / len(v['p']) for v in both.values())
    cr = statistics.mean(sum(v['c']) / len(v['c']) for v in both.values())
    gain = sum(len(v['p']) * (sum(v['c']) / len(v['c'])) - sum(v['p']) for v in both.values())
    return dict(configs=keys, n_tasks=len(both), poisoned_rate=pr, clean_rate=cr, gap_pts=100 * (cr - pr),
                runs=len(rows), extra_solves_if_clean=gain, upper_bound_pts=100 * gain / len(rows))


def caps_section(by_cfg, keys):
    out = {}
    for k in keys:
        rows = [r for r in by_cfg[k] if r['status'] == 'ok']
        cap = [r for r in rows if r['hit_time_cap'] or r['hit_call_cap']]
        free = [r for r in rows if not (r['hit_time_cap'] or r['hit_call_cap'])]
        out[k] = dict(runs=len(rows), time_cap=sum(r['hit_time_cap'] for r in rows),
                      call_cap=sum(r['hit_call_cap'] for r in rows), any_cap=len(cap),
                      any_cap_pct=100 * len(cap) / len(rows),
                      cap_solve_pct=100 * sum(r['resolved'] for r in cap) / len(cap) if cap else None,
                      free_solve_pct=100 * sum(r['resolved'] for r in free) / len(free) if free else None,
                      mean_agent_seconds=statistics.mean(r['agent_seconds'] for r in rows
                                                         if r['agent_seconds'] is not None))
    return out


# ---------------------------------------------------------------- A0 写回核对
A0_RE = re.compile(r'(?:^|/)formal_a0_31b/(?P<task>[^/]+)/A0_s0/(?P<kind>responses|requests)/step_(?P<step>\d+)\.json$')
A0_EV = re.compile(r'(?:^|/)formal_a0_31b/(?P<task>[^/]+)/A0_s0/events\.jsonl$')


def a0_writeback(tgz):
    """检查缺参数的 edit_file 调用是否按原参数写回下一次请求的历史。两遍顺序读归档，不解压。"""
    resp = collections.defaultdict(dict)
    fr = collections.defaultdict(dict)
    with tarfile.open(tgz, 'r|gz') as tf:
        for mem in tf:
            if not mem.isfile():
                continue
            m = A0_RE.search(mem.name)
            if m and m['kind'] == 'responses':
                try:
                    resp[m['task']][int(m['step'])] = json.load(tf.extractfile(mem))
                except ValueError:
                    pass
                continue
            m = A0_EV.search(mem.name)
            if m:
                for line in tf.extractfile(mem).read().decode('utf-8').splitlines():
                    if not line.strip():
                        continue
                    e = json.loads(line)
                    for p in (e.get('content') or {}).get('parts') or []:
                        f = p.get('function_response')
                        if f:
                            fr[m['task']][f['id']] = json.dumps(f.get('response'), ensure_ascii=False)
    seqs = {}
    need = set()
    for task in sorted(resp):
        seq = []
        for st in sorted(resp[task]):
            for p in (resp[task][st].get('content') or {}).get('parts') or []:
                fc = p.get('function_call')
                if fc and fc.get('name') in ('edit_file', 'write_file'):
                    seq.append(dict(step=st, id=fc['id'], name=fc['name'], args=fc.get('args') or {},
                                    missing=MISS in fr[task].get(fc['id'], '')))
        seqs[task] = seq
        for c in seq:
            if c['missing'] and c['name'] == 'edit_file':
                need.add((task, c['step'] + 1))
    hist = {}
    with tarfile.open(tgz, 'r|gz') as tf:
        for mem in tf:
            m = A0_RE.search(mem.name) if mem.isfile() else None
            if m and m['kind'] == 'requests' and (m['task'], int(m['step'])) in need:
                r = json.load(tf.extractfile(mem))
                calls = {}
                for item in r.get('contents', []):
                    for p in item.get('parts', []):
                        fc = p.get('function_call')
                        if fc:
                            calls[fc.get('id')] = fc.get('args')
                hist[(m['task'], int(m['step']))] = calls
    C = collections.Counter()
    markers = collections.Counter()
    for task, seq in seqs.items():
        poisoned = False
        for i, c in enumerate(seq):
            if c['missing']:
                long_arg = str(c['args'].get('new_string') or c['args'].get('content') or '')
                # 解析器的字符串分隔符原样出现在任何参数名或值里（被拆出的假参数也算）
                if '<|"|>' in json.dumps(c['args'], ensure_ascii=False).replace('\\"', '"'):
                    markers['literal_delimiter'] += 1
                elif re.search(r'`\s*,\s*\w+\s*:', long_arg):
                    markers['backtick'] += 1
                elif re.search(r'"\s*,\s*\w+\s*:', long_arg):
                    markers['quote'] += 1
                else:
                    markers['other'] += 1
            if c['name'] != 'edit_file':
                continue
            C['pre_n' if not poisoned else 'post_n'] += 1
            if c['missing']:
                C['pre_f' if not poisoned else 'post_f'] += 1
                if not poisoned:
                    C['first_failures'] += 1
                poisoned = True
                C['failed_edit_calls'] += 1
                h = hist.get((task, c['step'] + 1))
                if h is None:
                    C['no_next_request'] += 1
                elif c['id'] not in h:
                    C['next_request_without_call'] += 1
                else:
                    C['written_back'] += 1
                    C['written_back_identical_args'] += h[c['id']] == c['args']
                    vals = ' '.join(str(v) for v in (h[c['id']] or {}).values())
                    C['history_has_swallow_marker'] += bool(SWALLOW.search(vals))
                nxt = next((x for x in seq[i + 1:] if x['name'] == 'edit_file'), None)
                if nxt is not None:
                    C['followed_by_edit'] += 1
                    C['next_edit_identical'] += nxt['args'] == c['args']
                    C['next_edit_missing'] += nxt['missing']
    d = dict(C)
    d['missing_calls_all_tools'] = sum(markers.values())
    d['markers'] = dict(markers)
    d['tasks'] = len(seqs)
    return d


# ---------------------------------------------------------------- 输出
def fmt(x, d=1):
    return '-' if x is None else f'{x:.{d}f}'


def write_figures(out_dir, fig1, fig2, band=None):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return 'matplotlib 不可用，未画图'
    ink, ink2, grid, surface = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'
    c_cand, c_rerun = '#2a78d6', '#eb6834'
    plt.rcParams.update({'font.size': 9, 'axes.edgecolor': ink2, 'axes.labelcolor': ink2,
                         'xtick.color': ink2, 'ytick.color': ink2, 'text.color': ink})
    # 图 1：差值与 95% 区间；灰带 = 同配置两次全量差值的模拟 95% 范围（无真实差距时）
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    fig, ax = plt.subplots(figsize=(6.4, 3.9), facecolor=surface)
    ax.set_facecolor(surface)
    if band:
        ax.axvspan(band[0], band[1], color='#efeeea', zorder=0, lw=0)
    ys = list(range(len(fig1)))[::-1]
    for y, r in zip(ys, fig1):
        col = c_rerun if r['kind'] == 'rerun' else c_cand
        ax.plot([r['lo'], r['hi']], [y, y], color=col, lw=2, solid_capstyle='round', zorder=2)
        ax.plot(r['diff'], y, 'o', color=col, ms=6, mec=surface, mew=1.5, zorder=3)
        ax.text(9.6, y, f"{r['diff']:+.1f}", va='center', ha='right', fontsize=8, color=ink2)
    ax.axvline(0, color=ink2, lw=0.8, zorder=1)
    ax.set_xlim(-8, 9.8)
    ax.set_xticks(range(-8, 9, 2))
    ax.set_yticks(ys)
    ax.set_yticklabels([r['label'] for r in fig1])
    ax.set_xlabel('Difference in solve rate (percentage points), paired bootstrap 95% CI')
    ax.grid(axis='x', color=grid, lw=0.8)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    handles = [Line2D([], [], color=c_cand, marker='o', lw=2, label='Candidate vs. control'),
               Line2D([], [], color=c_rerun, marker='o', lw=2, label='Same config, re-run')]
    if band:
        handles.append(Patch(color='#efeeea', label='Re-run noise, 95% (simulated)'))
    ax.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.42, 1.0), ncol=3, frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, 'fig1_intervals.png'), dpi=200, facecolor=surface)
    plt.close(fig)
    # 图 2：第一次缺参数前后，每次 edit_file 的失败率
    fig, ax = plt.subplots(figsize=(6.4, 3.4), facecolor=surface)
    ax.set_facecolor(surface)
    ys = list(range(len(fig2)))[::-1]
    for y, r in zip(ys, fig2):
        ax.plot([r['pre'], r['post']], [y, y], color=grid, lw=2, zorder=1)
        ax.plot(r['pre'], y, 'o', color=c_cand, ms=7, mec=surface, mew=1.5, zorder=2)
        ax.plot(r['post'], y, 'o', color=c_rerun, ms=7, mec=surface, mew=1.5, zorder=2)
    ax.set_yticks(ys)
    ax.set_yticklabels([r['label'] for r in fig2])
    ax.set_xlim(0, 100)
    ax.set_xlabel('edit_file calls missing a required argument (%)')
    ax.grid(axis='x', color=grid, lw=0.8)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    ax.legend(handles=[Line2D([], [], color=c_cand, marker='o', lw=0, label='Before the first failure'),
                       Line2D([], [], color=c_rerun, marker='o', lw=0, label='After the first failure')],
              loc='lower center', bbox_to_anchor=(0.42, 1.0), ncol=2, frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, 'fig2_poison.png'), dpi=200, facecolor=surface)
    plt.close(fig)
    return 'ok'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--results', required=True, help='主赛/02_本地评测/结果')
    ap.add_argument('--a0', help='formal_a0_full_20261020.tgz（不给就跳过写回核对）')
    ap.add_argument('--out', required=True)
    ap.add_argument('--sims', type=int, default=4000, help='功效模拟次数（0 = 跳过）')
    ap.add_argument('--figures', action='store_true')
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)

    cache = {}
    by_cfg = {}
    for key, zname, dirs, kind, _ in CONFIGS:
        by_cfg[key] = load_config(a.results, key, zname, dirs, cache)
        print(f'{key}: {len(by_cfg[key])} 次运行', file=sys.stderr)

    S = {'configs': {}}
    for key, zname, dirs, kind, label in CONFIGS:
        rows = by_cfg[key]
        ok = [r for r in rows if r['status'] == 'ok']
        per_att = collections.Counter()
        for r in ok:
            per_att[r['attempt']] += r['resolved']
        S['configs'][key] = dict(zip=zname, dirs=dirs, kind=kind, label=label, runs=len(rows), ok=len(ok),
                                 tasks=len({r['task'] for r in ok}), solved=sum(r['resolved'] for r in ok),
                                 solved_by_attempt=dict(sorted(per_att.items())))

    # 配对比较（含同一配置两遍之间）
    comps = []
    for ka, kb, kind in COMPARISONS:
        res = paired(by_cfg[ka], by_cfg[kb])
        res.update(a=ka, b=kb, kind=kind, check=check_reported((ka, kb), res))
        comps.append(res)
    for k in FULL:
        rows = by_cfg[k]
        r0 = [r for r in rows if r['attempt'] == 0]
        r1 = [r for r in rows if r['attempt'] == 1]
        res = paired(r0, r1)
        res.update(a=f'{k}@a0', b=f'{k}@a1', kind='within', check=check_reported((f'{k}@a0', f'{k}@a1'), res))
        comps.append(res)
    S['comparisons'] = comps

    S['flips'] = {f'{x} vs {y}': flips(by_cfg[x], by_cfg[y])
                  for x, y in (('C01b_r2', 'C01b_r4'), ('C01b_r2', 'C01b_r7'), ('C01b_r4', 'C01b_r7'))}
    S['solvability_full20'] = solvability(by_cfg, FULL)
    S['solvability_c01b6'] = solvability(by_cfg, C01B_RUNS)
    S['power'] = power_section(by_cfg, a.sims, comps) if a.sims else dict(skipped='--sims 0')
    S['poison'], S['poison_total_full'] = poison_section(by_cfg, FULL)
    S['poison_gate'], _ = poison_section(by_cfg, ['r3_C01b', 'r3_C01c'])
    S['poison_within_task'] = {k: within_task_poison(by_cfg, [k]) for k in FULL}
    S['poison_within_task']['all_full'] = within_task_poison(by_cfg, FULL)
    S['caps'] = caps_section(by_cfg, FULL)
    S['a0_writeback'] = a0_writeback(a.a0) if a.a0 else dict(skipped='未给 --a0')

    # ---- 文件
    with open(os.path.join(a.out, 'runs.csv'), 'w', newline='', encoding='utf-8') as f:
        cols = ['config', 'run_dir', 'task', 'attempt', 'status', 'resolved', 'tool_calls', 'agent_seconds',
                'hit_time_cap', 'hit_call_cap', 'has_trace', 'calls_total', 'missing_calls', 'poisoned',
                'edit_pre_n', 'edit_pre_f', 'edit_post_n', 'edit_post_f', 'identical_failed_resend',
                'resend_after_missing', 'max_missing_chain']
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for key in by_cfg:
            for r in by_cfg[key]:
                w.writerow(r)
    with open(os.path.join(a.out, 'comparisons.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['a', 'b', 'kind', 'n_tasks', 'solved_a', 'runs_a', 'solved_b', 'runs_b', 'diff_pts',
                    'ci_lo', 'ci_hi', 'ci_lo_linear', 'ci_hi_linear', 'up', 'down', 'same', 'sign_p',
                    'reported', 'report_source', 'match'])
        for c in comps:
            ch = c['check'] or {}
            w.writerow([c['a'], c['b'], c['kind'], c['n_tasks'], c['solved_a'], c['runs_a'], c['solved_b'],
                        c['runs_b'], f"{c['diff_pts']:.2f}", f"{c['ci_idx'][0]:.2f}", f"{c['ci_idx'][1]:.2f}",
                        f"{c['ci_lin'][0]:.2f}", f"{c['ci_lin'][1]:.2f}", c['up'], c['down'], c['same'],
                        f"{c['sign_p']:.3f}", ch.get('reported', ''), ch.get('source', ''),
                        ch.get('match_method', '') if ch else ''])

    fig_label = {('base', 'C01b_r2'): 'C01b vs Base', ('base', 'C03b'): 'C03b vs Base',
                 ('base', 'C04'): 'C04 vs Base', ('C01b_r2', 'C03b'): 'C03b vs C01b',
                 ('C01b_r4', 'T2048'): 'T2048 vs C01b', ('C01b_r4', 'T3072'): 'T3072 vs C01b',
                 ('C01b_r4', 'X'): 'X vs C01b', ('C01b_r7', 'B30'): 'B30 vs C01b',
                 ('C01b_r2', 'C01b_r4'): 'C01b: round 4 vs round 2', ('C01b_r2', 'C01b_r7'): 'C01b: round 7 vs round 2',
                 ('C01b_r4', 'C01b_r7'): 'C01b: round 7 vs round 4'}
    fig1 = [dict(label=fig_label[(c['a'], c['b'])], kind=c['kind'], diff=c['diff_pts'], lo=c['ci_idx'][0],
                 hi=c['ci_idx'][1]) for c in comps if c['kind'] in ('candidate', 'rerun')]
    fig2 = [dict(label=LABEL[k], pre=S['poison'][k]['pre_rate_pct'], post=S['poison'][k]['post_rate_pct'],
                 pre_n=S['poison'][k]['edit_pre_n'], post_n=S['poison'][k]['edit_post_n'])
            for k in FULL]
    for name, rows in (('fig1_intervals.csv', fig1), ('fig2_poison.csv', fig2)):
        with open(os.path.join(a.out, name), 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    band = None
    if 'c01b6' in S['power']:
        band = S['power']['c01b6']['by_repeats'][2]['null_95_pts']
    S['figures'] = write_figures(a.out, fig1, fig2, band) if a.figures else '未加 --figures'

    json.dump(S, open(os.path.join(a.out, 'stats.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)
    open(os.path.join(a.out, 'summary.md'), 'w', encoding='utf-8').write(render_md(S))
    bad = [c for c in comps if c['check'] and not c['check']['match']]
    print(f"完成。报告值核对：{sum(1 for c in comps if c['check'])} 项，不一致 {len(bad)} 项", file=sys.stderr)
    for c in bad:
        print(f"  不一致：{c['b']} vs {c['a']} 本脚本 {c['diff_pts']:+.1f} [{c['ci_idx'][0]:+.1f}, {c['ci_idx'][1]:+.1f}]"
              f" / 线性 [{c['ci_lin'][0]:+.1f}, {c['ci_lin'][1]:+.1f}]，报告 {c['check']['reported']}", file=sys.stderr)
    return 1 if bad else 0


def render_md(S):
    L = ['# 论文赛写作数据（paper_stats.py 自动生成）', '',
         '所有数字由本脚本从结果包直接重算；口径写在每节开头。不要手改本文件，改脚本后重跑。', '']
    L += ['## 1 各配置解出数', '', '| 配置 | 类型 | 题数 | 运行 | 解出 | 各遍 |', '| --- | --- | ---: | ---: | ---: | --- |']
    for k, c in S['configs'].items():
        L.append(f"| {k} | {c['kind']} | {c['tasks']} | {c['ok']} | {c['solved']} | {c['solved_by_attempt']} |")
    L += ['', '## 2 配对比较', '',
          '每题先对各遍取平均，差值为候选减对照的每题成功率之差的均值；95% 区间为按题配对 bootstrap（seed 0，5000 次）。'
          '“核对”一栏对照各轮报告：index = 与 summarize.py 的取法一致，linear = 与线性分位数一致。', '',
          '| 候选 | 对照 | 类型 | 题 | 解出 B / A | 差（点） | 95% 区间 | 升/降/平 | 报告值 | 核对 |',
          '| --- | --- | --- | ---: | --- | ---: | --- | --- | --- | --- |']
    for c in S['comparisons']:
        ch = c['check']
        rep = f"{ch['reported'][0]:+.1f} [{ch['reported'][1]:+.1f}, {ch['reported'][2]:+.1f}]" if ch else ''
        L.append(f"| {c['b']} | {c['a']} | {c['kind']} | {c['n_tasks']} | {c['solved_b']}/{c['runs_b']} 对 "
                 f"{c['solved_a']}/{c['runs_a']} | {c['diff_pts']:+.1f} | [{c['ci_idx'][0]:+.1f}, {c['ci_idx'][1]:+.1f}] | "
                 f"{c['up']}/{c['down']}/{c['same']} | {rep} | {ch['match_method'] if ch else ''} |")
    L += ['', '## 3 同配置噪声', '', '同一题、同一遍标签在两次 C01b 全量之间结果不同的比例（描述性，两次不是同一随机样本）。', '']
    for k, v in S['flips'].items():
        L.append(f"- {k}：{v['flips']}/{v['n']}（{v['rate_pct']:.1f}%）")
    for key, title in (('solvability_full20', '10 个全量配置合并'), ('solvability_c01b6', 'C01b 三次全量')):
        s = S[key]
        L += ['', f'## 4 可解性：{title}（每题 {s["attempts_max"]} 次尝试）', '',
              f"- 从未解出 {s['never']} 题，每次都解出 {s['always']} 题，时有时无 {s['mixed']} 题（共 {s['n_tasks']} 题）",
              f"- 按仓库：{s['by_repo']}", f"- 每题成功次数分布：{s['distribution']}"]
    P = S['power']
    L += ['', '## 5 分辨率与功效模拟', '']
    if 'skipped' in P:
        L.append(f"跳过：{P['skipped']}")
    else:
        L.append(f"假设：{P['assumption']}")
        o = P['observed_ci']
        L += ['', f"- 实际 {o['n']} 个全量比较（含 3 个同配置重跑）的 95% 区间半宽：平均 {o['mean_half_width_pts']:.1f} 点"
                  f"（{o['min']:.1f}–{o['max']:.1f}）；按正态近似，80% 功效需要真实差约 {o['implied_mde80_pts']:.1f} 点"]
        for ek in ('c01b6', 'pool20'):
            e = P[ek]
            L += ['', f"### 估计法 {ek}：{e['description']}", '',
                  f"- 同配置两次全量（125 题 × 2 遍）解出数之差的标准差：{e['sd_diff_two_runs_solves']:.2f} 次"
                  f"（{e['sd_diff_two_runs_pts']:.2f} 点）；正态近似下 80% 功效需要 {e['normal_approx_mde80_pts']:.1f} 点", '',
                  '| 每题遍数 | 每配置运行 | 零假设 95% 范围（点） | ' + ' | '.join(f'真实差 {d}' for d in SHOW) +
                  ' | 80% 功效所需（点） |',
                  '| ---: | ---: | --- | ' + ' | '.join('---:' for _ in SHOW) + ' | ---: |']
            for R, v in e['by_repeats'].items():
                cells = ' | '.join(f"{v['power'][str(d)]:.2f}" for d in SHOW)
                L.append(f"| {R} | {v['runs_per_config']} | [{v['null_95_pts'][0]:+.1f}, {v['null_95_pts'][1]:+.1f}] | "
                         f"{cells} | {fmt(v['mde80_pts'])} |")
    L += ['', '## 6 坏调用的自我复制', '',
          '中毒 = 一次运行里第一次 edit_file 缺必填参数。“之前”包含这第一次失败本身；“之后”是同一运行里其后的 edit_file。', '',
          '“缺参数后原样重发”= 缺参数调用的下一次调用与它完全相同（第三轮 recovery_metrics.py 的主指标）；'
          '“原样重发失败调用”= 任一失败调用后紧跟同参数、同错误的调用。', '',
          '| 配置 | 之前失败 | 之后失败 | 中毒运行（解出率） | 未中毒运行解出率 | 缺参数调用 | 缺参数后原样重发 | 原样重发失败调用 | 最长连续缺参数 |',
          '| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |']
    rows = list(S['poison'].items()) + [('合计（全量）', S['poison_total_full'])] + list(S['poison_gate'].items())
    for k, c in rows:
        L.append(f"| {k} | {c['edit_pre_f']}/{c['edit_pre_n']}（{fmt(c['pre_rate_pct'])}%） | "
                 f"{c['edit_post_f']}/{c['edit_post_n']}（{fmt(c['post_rate_pct'], 0)}%） | {c['poisoned']}/{c['runs']}"
                 f"（{fmt(c['poisoned_solve_pct'], 0)}%） | {fmt(c['clean_solve_pct'], 0)}% | {c['missing_calls']} | "
                 f"{c['resend_after_missing']} | {c['identical_failed_resend']} | {c['max_missing_chain']} |")
    L += ['', '同一题内比较（只用同时有中毒和未中毒运行的题；观察关联，不是因果）：', '']
    for k, v in S['poison_within_task'].items():
        if v.get('n_tasks'):
            L.append(f"- {k}：{v['n_tasks']} 题，中毒 {v['poisoned_rate']:.2f} 对未中毒 {v['clean_rate']:.2f}，"
                     f"差 {v['gap_pts']:.1f} 点；全部换成未中毒的解出率，总解出率最多变化 {v['upper_bound_pts']:+.1f} 点")
    W = S['a0_writeback']
    L += ['', '## 7 A0：坏调用是否写回历史', '']
    if 'skipped' in W:
        L.append(f"跳过：{W['skipped']}")
    else:
        L += [f"- 30 题 A0 长轨迹（{W['tasks']} 题有记录）里缺参数的 edit_file 调用 {W['failed_edit_calls']} 次",
              f"- 下一次请求的历史里带着同一调用：{W.get('written_back', 0)}/{W['failed_edit_calls']}；参数逐字相同 "
              f"{W.get('written_back_identical_args', 0)}；历史里可见吞参数痕迹 {W.get('history_has_swallow_marker', 0)}",
              f"- 之后的下一次 edit_file：与失败调用完全相同 {W.get('next_edit_identical', 0)}/{W.get('followed_by_edit', 0)}，"
              f"仍缺参数 {W.get('next_edit_missing', 0)}/{W.get('followed_by_edit', 0)}",
              f"- 第一次失败之前 {W.get('pre_f', 0)}/{W.get('pre_n', 0)}，之后 {W.get('post_f', 0)}/{W.get('post_n', 0)}",
              f"- 全部缺参数调用（含 write_file）{W['missing_calls_all_tools']} 次，长参数结尾：{W['markers']}"]
    L += ['', '## 8 碰额度', '', '| 配置 | 碰时限 | 碰调用上限 | 任一（占比） | 碰额度解出率 | 未碰解出率 | 平均代理用时（秒） |',
          '| --- | ---: | ---: | --- | ---: | ---: | ---: |']
    for k, c in S['caps'].items():
        L.append(f"| {k} | {c['time_cap']} | {c['call_cap']} | {c['any_cap']}（{c['any_cap_pct']:.0f}%） | "
                 f"{fmt(c['cap_solve_pct'], 0)}% | {fmt(c['free_solve_pct'], 0)}% | {c['mean_agent_seconds']:.1f} |")
    L += ['', f"图：{S['figures']}", '']
    return '\n'.join(L)


if __name__ == '__main__':
    sys.exit(main())
