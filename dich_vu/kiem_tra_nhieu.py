"""Basic acoustic quality checks for OneStep microphone recordings.

These are *heuristic* signal checks, not ASR confidence or medically validated metrics.
No raw audio is persisted by this module.
"""
import os
import numpy as np


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def kiem_tra_chat_luong(audio, rate, noise_mean_abs=None, min_seconds=None):
    """Return (accepted, reason, stats), without modifying the original recording.

    `noise_mean_abs` comes from the initial calibration in native PCM16 units.
    Mean absolute PCM levels are heuristic, not an exact physical SNR estimate.
    """
    x = np.asarray(audio, dtype=np.int16).reshape(-1)
    rate = max(int(rate), 1)
    duration = len(x) / rate
    stats = {"seconds": round(duration, 2), "mean_abs": 0.0,
             "clipping_ratio": 0.0, "speech_noise_db_est": None}
    if not x.size:
        return False, 'Không ghi nhận được âm thanh. Bạn nói lại nhé.', stats
    v = np.abs(x.astype(np.float32))
    stats['mean_abs'] = round(float(v.mean()), 1)
    stats['clipping_ratio'] = round(float(np.mean(v >= 32500)), 4)
    min_dur = max(0., float(min_seconds) if min_seconds is not None else _env_float('ONESTEP_ASR_MIN_SECONDS', .38))
    if duration < min_dur:
        return False, 'Mình nghe hơi ngắn. Bạn nói lại rõ hơn nhé.', stats
    if stats['clipping_ratio'] > _env_float('ONESTEP_ASR_MAX_CLIP_RATIO', .07):
        return False, 'Âm thanh bị rè hoặc quá lớn. Bạn thử để mic xa hơn một chút nhé.', stats
    if stats['mean_abs'] < _env_float('ONESTEP_ASR_MIN_MEAN_ABS', 90):
        return False, 'Âm thanh quá nhỏ. Bạn thử nói gần mic hơn nhé.', stats
    if noise_mean_abs is not None and noise_mean_abs > 0:
        # Compare overall recording mean to original noise-only ambient level.
        # During quiet periods mean may be lower than real speech, so use loose gate.
        ratio = max(stats['mean_abs'] / max(float(noise_mean_abs), 1.), 1e-9)
        import math
        db = 20.0 * math.log10(ratio)
        stats['speech_noise_db_est'] = round(db, 1)
        min_ratio_db = _env_float('ONESTEP_ASR_MIN_SPEECH_NOISE_DB', 3.0)
        if db < min_ratio_db and float(noise_mean_abs) >= _env_float('ONESTEP_ASR_NOISY_AMBIENT_MIN', 350):
            return False, 'Xung quanh đang hơi ồn nên mình chưa nghe rõ. Bạn thử nói lại hoặc nhập bằng bàn phím nhé.', stats
    return True, '', stats
