import os
import queue
from collections import deque
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
import speech_recognition as sr

from dich_vu.quan_ly_am_thanh import audio_lock, sau_dau_vao_giai_phong
from dich_vu.cai_dat_nguoi_dung import tai_cai_dat
from dich_vu.kiem_tra_nhieu import kiem_tra_chat_luong

from cau_hinh import (
    VOICE_SAMPLE_RATE,
    VOICE_BLOCK_SIZE,
    VOICE_START_TIMEOUT,
    VOICE_SILENCE_DURATION,
    VOICE_MAX_RECORD_SECONDS,
    VOICE_NOISE_CALIBRATION_SECONDS,
    VOICE_THRESHOLD_MULTIPLIER,
    VOICE_MIN_THRESHOLD,
    VOICE_MAX_THRESHOLD,
    STT_ONLINE_FIRST,
    WHISPER_EXE,
    WHISPER_MODEL,
)


class DichVuNhanDangGiongNoi:
    """Thu âm từ microphone mặc định của hệ điều hành và nhận dạng giọng nói.

    Quan trọng:
    - Microphone được mở ở sample rate native do Ubuntu/PulseAudio/PipeWire cung cấp.
    - Audio chỉ được resample về VOICE_SAMPLE_RATE (mặc định 16 kHz) SAU KHI thu.
    - Cách này tránh lỗi PortAudio ``Invalid sample rate`` với microphone chỉ hỗ trợ
      44.1 kHz/48 kHz trực tiếp.
    """

    def __init__(self, on_audio_level=None):
        self.last_threshold = VOICE_MIN_THRESHOLD
        self.on_audio_level = on_audio_level
        self.last_input_device = None
        self.last_native_sample_rate = None
        self.last_noise_mean_abs = None
        self.last_quality = {}
        self.last_quality_error = ""

    def _lay_micro_mac_dinh(self):
        """Trả về thông tin input mặc định và sample rate native.

        Không ép/chuyển ``sd.default.device`` sang ``int`` vì ở một số phiên bản
        python-sounddevice giá trị này là ``_InputOutputPair``. Thay vào đó, để
        PortAudio/PulseAudio/PipeWire tự phân giải input mặc định của Ubuntu.
        """
        settings = tai_cai_dat()
        input_device = settings.get("audio_input_device")
        if input_device is None:
            info = sd.query_devices(kind="input")
        else:
            info = sd.query_devices(int(input_device), "input")

        native_rate = int(round(float(info["default_samplerate"])))
        if native_rate <= 0:
            raise RuntimeError("Microphone không cung cấp sample rate hợp lệ")

        self.last_input_device = input_device
        self.last_native_sample_rate = native_rate
        return input_device, info, native_rate

    def _bao_muc_am_thanh(self, data):
        """Tính RMS/Peak chuẩn hóa và gửi ra UI/console."""
        if data is None or len(data) == 0:
            return None

        x = data.astype(np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(x * x)) / 32768.0)
        peak = float(np.max(np.abs(x)) / 32768.0)
        rms = max(0.0, min(1.0, rms))
        peak = max(0.0, min(1.0, peak))

        if self.on_audio_level is not None:
            try:
                self.on_audio_level(rms, peak)
            except Exception as e:
                print("[AUDIO LEVEL CALLBACK WARN]", e)

        return rms, peak

    @staticmethod
    def _resample_int16(audio, source_rate, target_rate):
        """Resample mono int16 bằng nội suy tuyến tính, không cần scipy/librosa."""
        if audio is None or len(audio) == 0:
            return audio

        source_rate = int(source_rate)
        target_rate = int(target_rate)
        x = np.asarray(audio, dtype=np.int16).reshape(-1)

        if source_rate == target_rate:
            return x
        if source_rate <= 0 or target_rate <= 0:
            raise ValueError("Sample rate phải lớn hơn 0")

        target_len = max(1, int(round(len(x) * target_rate / source_rate)))
        old_positions = np.arange(len(x), dtype=np.float64)
        new_positions = np.linspace(0, len(x) - 1, target_len, dtype=np.float64)
        y = np.interp(new_positions, old_positions, x.astype(np.float64))
        return np.clip(np.rint(y), -32768, 32767).astype(np.int16)

    def _ghi_den_khi_im_lang(self, confirmation_mode=False):
        # ONESTEP_PATCH34_SHORT_REPLY: separate endpoint settings for 1-3 word replies.
        # A shorter endpoint is useful after Buddy has asked a confirmation question.
        # It is not a license to treat fan noise as speech.
        capture_start_timeout = (8.0 if confirmation_mode else VOICE_START_TIMEOUT)
        calibration_seconds = (0.30 if confirmation_mode else VOICE_NOISE_CALIBRATION_SECONDS)
        silence_seconds = (0.90 if confirmation_mode else VOICE_SILENCE_DURATION)
        max_record_seconds = (6.0 if confirmation_mode else VOICE_MAX_RECORD_SECONDS)
        if confirmation_mode:
            print('[STT REPLY MODE] short=True calibration=0.30s silence=0.90s pre_roll=0.35s start_timeout=8.0s')
        q = queue.Queue()
        chunks = []
        pre_roll = deque(maxlen=12)  # ~0.35s at 44.1 kHz for 512 samples/16k block
        started = False
        silence_start = None
        speech_start = None
        noise_levels = []
        self.last_noise_mean_abs = None
        calibration_start = time.time()
        threshold = VOICE_MIN_THRESHOLD

        input_device, device_info, native_rate = self._lay_micro_mac_dinh()
        device_name = device_info.get("name", "default")

        # VOICE_BLOCK_SIZE vốn được chọn cho 16 kHz. Quy đổi số frame để giữ
        # khoảng thời gian mỗi block gần tương đương khi thu ở 44.1/48 kHz.
        native_block_size = max(
            256,
            int(round(VOICE_BLOCK_SIZE * native_rate / VOICE_SAMPLE_RATE)),
        )

        def ham_goi_lai(indata, frames, time_info, status):
            if status:
                print("[AUDIO]", status)
            q.put(indata.copy())

        print("[STT] Đang chờ bạn nói...")
        print(
            f"[MIC] Input: {device_name} (device={input_device if input_device is not None else 'default'}) | "
            f"native={native_rate} Hz | STT={VOICE_SAMPLE_RATE} Hz"
        )

        stream_kwargs = dict(
            samplerate=native_rate,
            channels=1,
            dtype="int16",
            blocksize=native_block_size,
            callback=ham_goi_lai,
        )
        # Nếu PortAudio đã cung cấp một index cụ thể thì truyền index đó.
        # Nếu không, bỏ device để dùng đúng default source của Ubuntu.
        if input_device is not None:
            stream_kwargs["device"] = input_device

        with sd.InputStream(**stream_kwargs):
            wait_start = time.time()

            while True:
                data = q.get()
                level = float(np.abs(data.astype(np.int32)).mean())
                muc = self._bao_muc_am_thanh(data)
                if muc is not None:
                    rms, peak = muc
                    print(
                        f"[MIC] RMS={rms:.4f} Peak={peak:.4f} "
                        f"MeanAbs={level:.0f} Threshold={threshold}",
                        flush=True,
                    )

                if not started and confirmation_mode:
                    pre_roll.append(data.copy())

                if (
                    not started
                    and time.time() - calibration_start
                    < calibration_seconds
                ):
                    noise_levels.append(level)
                    continue

                if noise_levels and not started:
                    noise = float(np.median(noise_levels))
                    self.last_noise_mean_abs = noise
                    threshold = int(
                        max(
                            VOICE_MIN_THRESHOLD,
                            min(
                                VOICE_MAX_THRESHOLD,
                                noise * (min(VOICE_THRESHOLD_MULTIPLIER, 2.20) if confirmation_mode else VOICE_THRESHOLD_MULTIPLIER),
                            ),
                        )
                    )
                    self.last_threshold = threshold
                    noise_levels = []
                    print(f"[STT] Noise threshold = {threshold}")

                if not started:
                    if level > threshold:
                        started = True
                        speech_start = time.time()
                        if confirmation_mode:
                            chunks.extend(pre_roll)
                            pre_roll.clear()
                        else:
                            chunks.append(data)
                        print("[STT] Bắt đầu nói")
                    elif time.time() - wait_start > capture_start_timeout:
                        print("[STT] Không phát hiện giọng nói")
                        return None
                    continue

                chunks.append(data)

                if level > threshold:
                    silence_start = None
                else:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start >= silence_seconds:
                        print("[STT] Im lặng -> dừng thu")
                        break

                if time.time() - speech_start >= max_record_seconds:
                    print("[STT] Đạt giới hạn ghi âm")
                    break

        if not chunks:
            return None

        native_audio = np.concatenate(chunks, axis=0).reshape(-1)
        if native_rate != VOICE_SAMPLE_RATE:
            t0 = time.perf_counter()
            audio_16k = self._resample_int16(
                native_audio,
                native_rate,
                VOICE_SAMPLE_RATE,
            )
            print(
                f"[MIC] Resample {native_rate} -> {VOICE_SAMPLE_RATE} Hz: "
                f"{len(native_audio)} -> {len(audio_16k)} samples "
                f"({time.perf_counter() - t0:.3f}s)"
            )
            return audio_16k

        return native_audio.astype(np.int16, copy=False)

    def lang_nghe_mot_lan(self, confirmation_mode=False):
        with audio_lock:
            try:
                audio = self._ghi_den_khi_im_lang(confirmation_mode=confirmation_mode)
            finally:
                try:
                    sd.stop()
                except Exception as e:
                    print("[AUDIO STT STOP WARN]", e)

        sau_dau_vao_giai_phong()

        if audio is None:
            return ""

        # For a short ACK, only reduce minimum duration; do NOT bypass clipping,
        # overall loudness or ambient SNR checks. Restore env in finally.
        if confirmation_mode:
            from dich_vu.kiem_tra_nhieu import kiem_tra_chat_luong as check_quality
            # Use the same quality checker, with per-turn duration parameter
            # rather than global environment mutation.
            ok, reason, stats = check_quality(
                audio, VOICE_SAMPLE_RATE, self.last_noise_mean_abs,
                min_seconds=0.16,
            )
        else:
            ok, reason, stats = kiem_tra_chat_luong(
                audio, VOICE_SAMPLE_RATE, self.last_noise_mean_abs
            )
        self.last_quality = stats
        self.last_quality_error = reason
        print(f"[ASR QUALITY] ok={ok} stats={stats} reason={reason!r}")
        if not ok:
            # Return empty result: Buddy's existing UI requests a repetition.
            # No voice command reaches the intent router / task creation code.
            return ""

        errors = []

        if STT_ONLINE_FIRST:
            try:
                online_text = self._google(audio)
                if online_text:
                    return online_text
                print('[STT REPLY] Online recognition empty; trying Whisper')
            except Exception as e:
                print("[STT ONLINE ERROR]", e)
                errors.append("Google STT: " + str(e))

        # Do not try to launch an unavailable whisper-cli (typical Jetson
        # installation). Treat an unrecognized short reply as an empty transcript;
        # the pending confirmation remains active and the user can retry/type.
        whisper_path = Path(str(WHISPER_EXE))
        if not whisper_path.is_file() or not os.access(whisper_path, os.X_OK):
            print(f"[STT FALLBACK] whisper-cli unavailable: {whisper_path}; keeping confirmation pending")
            if errors:
                print("[STT FALLBACK] online details:", " | ".join(errors))
            return ""
        try:
            return self._whisper(audio)
        except Exception as e:
            errors.append("Whisper: " + str(e))

        # Network / recognizer failures should not destroy pending state.
        print("[STT FALLBACK] no transcript:", " | ".join(errors))
        return ""

    def _google(self, audio):
        rec = sr.Recognizer()
        data = sr.AudioData(
            np.asarray(audio, dtype=np.int16).tobytes(),
            VOICE_SAMPLE_RATE,
            2,
        )

        try:
            return rec.recognize_google(data, language="vi-VN").strip()
        except sr.UnknownValueError:
            return ""

    def _whisper(self, audio):
        wav = Path("input.wav").resolve()

        with wave.open(str(wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(VOICE_SAMPLE_RATE)
            wf.writeframes(np.asarray(audio, dtype=np.int16).tobytes())

        exe = str(WHISPER_EXE)
        if os.name == "nt" and not exe.lower().endswith(".exe"):
            exe += ".exe"

        if not Path(exe).exists():
            raise FileNotFoundError(f"Không tìm thấy whisper-cli: {exe}")

        r = subprocess.run(
            [
                exe,
                "-m", str(WHISPER_MODEL),
                "-l", "vi",
                "-f", str(wav),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )

        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "whisper.cpp failed")

        out = []
        for line in r.stdout.splitlines():
            if "]" in line:
                s = line.split("]", 1)[1].strip()
                if s:
                    out.append(s)

        return " ".join(out).strip()
