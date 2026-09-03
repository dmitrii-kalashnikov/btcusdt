from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import KNeighborsRegressor
from sklearn.preprocessing import StandardScaler

import btc_baseline as b

OUT = Path('leading_signal_artifacts')
OUT.mkdir(exist_ok=True)
FEATURES = list(b.FEATURES)
HORIZONS = (7, 30, 90, 180, 365)
K = 15
STRIDE = 7


def predict_knn(frame: pd.DataFrame, i: int, h: int) -> float:
    target = f'fwd_ret_{h}d'
    train_end = i - h
    if train_end < 500:
        raise RuntimeError('insufficient history')
    train = frame.iloc[:train_end + 1].dropna(subset=FEATURES + [target]).copy()
    x_now = frame.loc[[i], FEATURES]
    if x_now.isna().any(axis=None):
        return float('nan')
    scaler = StandardScaler().fit(train[FEATURES])
    X = scaler.transform(train[FEATURES])
    x = scaler.transform(x_now)
    k = min(K, len(train))
    model = KNeighborsRegressor(n_neighbors=k, weights='distance', metric='euclidean')
    model.fit(X, train[target].to_numpy(float))
    return float(model.predict(x)[0])


def origins(frame: pd.DataFrame, start: str, end: str):
    s = pd.Timestamp(start, tz='UTC')
    e = pd.Timestamp(end + ' 23:59:59', tz='UTC')
    idx = frame.index[(frame.time >= s) & (frame.time <= e)].tolist()
    if not idx:
        return []
    t0 = frame.at[idx[0], 'time']
    return [i for i in idx if (frame.at[i, 'time'] - t0).days % STRIDE == 0]


def evaluate(frame: pd.DataFrame, split: str, start: str, end: str) -> pd.DataFrame:
    rows = []
    for i in origins(frame, start, end):
        for h in HORIZONS:
            actual = frame.at[i, f'fwd_ret_{h}d']
            if pd.isna(actual):
                continue
            pred = predict_knn(frame, i, h)
            if not np.isfinite(pred):
                continue
            rows.append({
                'split': split,
                'time': frame.at[i, 'time'],
                'horizon_days': h,
                'prediction': pred,
                'actual': float(actual),
            })
    return pd.DataFrame(rows)


def score(pred: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (split, h), g in pred.groupby(['split', 'horizon_days']):
        err = g.prediction - g.actual
        rows.append({
            'split': split,
            'horizon_days': int(h),
            'n': int(len(g)),
            'directional_accuracy': float((np.sign(g.prediction) == np.sign(g.actual)).mean()),
            'mae_log_return': float(np.abs(err).mean()),
            'rmse_log_return': float(np.sqrt(np.mean(err ** 2))),
            'median_abs_error': float(np.median(np.abs(err))),
            'mean_actual_return_pct': float((np.exp(g.actual) - 1).mean()),
            'mean_predicted_return_pct': float((np.exp(g.prediction) - 1).mean()),
        })
    return pd.DataFrame(rows)


def nonoverlap(pred: pd.DataFrame) -> pd.DataFrame:
    keep = []
    for (split, h), g in pred.sort_values('time').groupby(['split', 'horizon_days']):
        last = None
        for _, r in g.iterrows():
            if last is None or (r.time - last).days >= int(h):
                keep.append(r)
                last = r.time
    return score(pd.DataFrame(keep)) if keep else pd.DataFrame()


def main():
    daily = b.download_binance_daily()
    frame = b.add_features_targets(daily)
    val = evaluate(frame, 'validation_2022_2023', '2022-01-01', '2023-12-31')
    consumed = evaluate(frame, 'diagnostic_consumed_2024_2025', '2024-01-01', '2025-12-31')
    post = evaluate(frame, 'post_holdout_2026_ytd', '2026-01-01', '2026-08-31')
    pred = pd.concat([val, consumed, post], ignore_index=True)
    metrics = score(pred)
    robust = nonoverlap(pred)
    pred.to_csv(OUT / 'analog_knn_predictions.csv', index=False)
    metrics.to_csv(OUT / 'analog_knn_metrics.csv', index=False)
    robust.to_csv(OUT / 'analog_knn_nonoverlap.csv', index=False)
    summary = {
        'experiment': 'leading-signal-diagnostic-v1',
        'method': 'fixed KNN historical analog, k=15, distance weighted, standardized frozen price features',
        'warning': '2024-2025 is already consumed; 2026 YTD is diagnostic, not pristine prospective evidence because architecture was designed after observing part of 2026.',
        'no_leakage': 'training labels must fully realize before each origin: train_end=i-h',
        'metrics': metrics.to_dict('records'),
        'nonoverlap': robust.to_dict('records'),
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, default=str))
    print(metrics.to_string(index=False))
    print('\nNONOVERLAP')
    print(robust.to_string(index=False))


if __name__ == '__main__':
    main()
