import os
import queue
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
import speech_recognition as sr

from dich_vu.quan_ly_am_thanh import audio_lock, sau_dau_vao_giai_phong

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

    def _lay_micro_mac_dinh(self):
        """Trả về thông tin input mặc định và sample rate native.

        Không ép/chuyển ``sd.default.device`` sang ``int`` vì ở một số phiên bản
        python-sounddevice giá trị này là ``_InputOutputPair``. Thay vào đó, để
        PortAudio/PulseAudio/PipeWire tự phân giải input mặc định của Ubuntu.
        """
        info = sd.query_devices(kind="input")
        native_rate = int(round(float(info["default_samplerate"])))
        if native_rate <= 0:
            raise RuntimeError("Microphone mặc định không cung cấp sample rate hợp lệ")

        # None có nghĩa: không truyền device=... vào InputStream, dùng đúng
        # microphone mặc định mà Ubuntu/PulseAudio/PipeWire đang chọn.
        input_device = None
        self.last_input_device = None
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

    def _ghi_den_khi_im_lang(self):
        q = queue.Queue()
        chunks = []
        started = False
        silence_start = None
        speech_start = None
        noise_levels = []
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
            f"[MIC] Default input: {device_name} | "
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

                if (
                    not started
                    and time.time() - calibration_start
                    < VOICE_NOISE_CALIBRATION_SECONDS
                ):
                    noise_levels.append(level)
                    continue

                if noise_levels and not started:
                    noise = float(np.median(noise_levels))
                    threshold = int(
                        max(
                            VOICE_MIN_THRESHOLD,
                            min(
                                VOICE_MAX_THRESHOLD,
                                noise * VOICE_THRESHOLD_MULTIPLIER,
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
                        chunks.append(data)
                        print("[STT] Bắt đầu nói")
                    elif time.time() - wait_start > VOICE_START_TIMEOUT:
                        print("[STT] Không phát hiện giọng nói")
                        return None
                    continue

                chunks.append(data)

                if level > threshold:
                    silence_start = None
                else:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start >= VOICE_SILENCE_DURATION:
                        print("[STT] Im lặng -> dừng thu")
                        break

                if time.time() - speech_start >= VOICE_MAX_RECORD_SECONDS:
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

    def lang_nghe_mot_lan(self):
        with audio_lock:
            try:
                audio = self._ghi_den_khi_im_lang()
            finally:
                try:
                    sd.stop()
                except Exception as e:
                    print("[AUDIO STT STOP WARN]", e)

        sau_dau_vao_giai_phong()

        if audio is None:
            return ""

        errors = []

        if STT_ONLINE_FIRST:
            try:
                return self._google(audio)
            except Exception as e:
                print("[STT ONLINE ERROR]", e)
                errors.append("Google STT: " + str(e))

        try:
            return self._whisper(audio)
        except Exception as e:
            errors.append("Whisper: " + str(e))

        raise RuntimeError(" | ".join(errors))

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
