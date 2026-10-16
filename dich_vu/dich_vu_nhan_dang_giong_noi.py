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
    def __init__(self):
        self.last_threshold=VOICE_MIN_THRESHOLD

    def _ghi_den_khi_im_lang(self):
        q=queue.Queue()
        chunks=[]
        started=False
        silence_start=None
        speech_start=None
        noise_levels=[]
        calibration_start=time.time()
        threshold=VOICE_MIN_THRESHOLD

        def ham_goi_lai(indata,frames,time_info,status):
            if status:
                print("[AUDIO]",status)
            q.put(indata.copy())

        print("[STT] Đang chờ bạn nói...")

        with sd.InputStream(
            samplerate=VOICE_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=VOICE_BLOCK_SIZE,
        ):
            wait_start=time.time()

            while True:
                data=q.get()
                level=float(
                    np.abs(data.astype(np.int32)).mean()
                )

                # Hiệu chỉnh nhiễu môi trường trước.
                if (
                    not started
                    and time.time()-calibration_start
                    < VOICE_NOISE_CALIBRATION_SECONDS
                ):
                    noise_levels.append(level)
                    continue

                if noise_levels and not started:
                    noise=float(np.median(noise_levels))
                    threshold=int(
                        max(
                            VOICE_MIN_THRESHOLD,
                            min(
                                VOICE_MAX_THRESHOLD,
                                noise*VOICE_THRESHOLD_MULTIPLIER
                            )
                        )
                    )
                    self.last_threshold=threshold
                    noise_levels=[]
                    print(f"[STT] Noise threshold = {threshold}")

                if not started:
                    if level>threshold:
                        started=True
                        speech_start=time.time()
                        chunks.append(data)
                        print("[STT] Bắt đầu nói")

                    elif time.time()-wait_start>VOICE_START_TIMEOUT:
                        print("[STT] Không phát hiện giọng nói")
                        return None

                    continue

                chunks.append(data)

                if level>threshold:
                    silence_start=None
                else:
                    if silence_start is None:
                        silence_start=time.time()
                    elif time.time()-silence_start>=VOICE_SILENCE_DURATION:
                        print("[STT] Im lặng -> dừng thu")
                        break

                if time.time()-speech_start>=VOICE_MAX_RECORD_SECONDS:
                    print("[STT] Đạt giới hạn ghi âm")
                    break

        if not chunks:
            return None

        return np.concatenate(chunks,axis=0)

    def lang_nghe_mot_lan(self):
        # STT giữ độc quyền thiết bị âm thanh trong lúc ghi âm.
        with audio_lock:
            try:
                audio=self._ghi_den_khi_im_lang()
            finally:
                # Chủ động giải phóng PortAudio/ALSA trước khi bộ điều phối hoặc TTS bắt đầu.
                try:
                    sd.stop()
                except Exception as e:
                    print("[AUDIO STT STOP WARN]", e)

        sau_dau_vao_giai_phong()

        if audio is None:
            return ""

        errors=[]

        if STT_ONLINE_FIRST:
            try:
                return self._google(audio)
            except Exception as e:
                print("[STT ONLINE ERROR]",e)
                errors.append("Google STT: "+str(e))

        try:
            return self._whisper(audio)
        except Exception as e:
            errors.append("Whisper: "+str(e))

        raise RuntimeError(" | ".join(errors))

    def _google(self,audio):
        rec=sr.Recognizer()
        data=sr.AudioData(
            audio.tobytes(),
            VOICE_SAMPLE_RATE,
            2
        )

        try:
            return rec.recognize_google(
                data,
                language="vi-VN"
            ).strip()
        except sr.UnknownValueError:
            return ""

    def _whisper(self,audio):
        wav=Path("input.wav").resolve()

        with wave.open(str(wav),"wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(VOICE_SAMPLE_RATE)
            wf.writeframes(audio.tobytes())

        exe=str(WHISPER_EXE)

        if os.name=="nt" and not exe.lower().endswith(".exe"):
            exe += ".exe"

        if not Path(exe).exists():
            raise FileNotFoundError(
                f"Không tìm thấy whisper-cli: {exe}"
            )

        r=subprocess.run(
            [
                exe,
                "-m",str(WHISPER_MODEL),
                "-l","vi",
                "-f",str(wav)
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )

        if r.returncode!=0:
            raise RuntimeError(
                r.stderr.strip() or "whisper.cpp failed"
            )

        out=[]
        for line in r.stdout.splitlines():
            if "]" in line:
                s=line.split("]",1)[1].strip()
                if s:
                    out.append(s)

        return " ".join(out).strip()
