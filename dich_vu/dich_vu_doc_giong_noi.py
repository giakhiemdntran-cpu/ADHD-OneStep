import asyncio
import os
import queue
import tempfile
import threading
import time

import numpy as np

from cau_hinh import (
    EDGE_TTS_RATE,
    EDGE_TTS_VOICE,
    TTS_EDGE_FALLBACK,
    TTS_ENGINE,
    TTS_PYTTSX3_FALLBACK,
    VIENEU_BACKEND,
    VIENEU_FIRST_AUDIO_TIMEOUT,
    VIENEU_PRELOAD,
    VIENEU_SAMPLE_RATE,
    VIENEU_START_BUFFER_MS,
    VIENEU_STREAM_STALL_TIMEOUT,
    VIENEU_VOICE,
)
from dich_vu.quan_ly_am_thanh import audio_lock, sau_dau_ra_giai_phong
from dich_vu.cai_dat_nguoi_dung import tai_cai_dat


class VieNeuStreamError(RuntimeError):
    """Lỗi streaming VieNeu; played_audio cho biết loa đã phát được một phần câu hay chưa."""

    def __init__(self, message, played_audio=False):
        super().__init__(message)
        self.played_audio = bool(played_audio)


class DichVuDocGiongNoi:
    """TTS cho OneStep.

    Engine chính: VieNeu-TTS v3 Turbo streaming (PCM float32 @ 48 kHz).
    Fallback: Edge TTS -> pyttsx3.

    VieNeu phát trực tiếp bằng sounddevice.OutputStream, không tạo MP3/WAV tạm.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self._pygame = None
        self._vieneu = None
        self._vieneu_lock = threading.Lock()
        self._stop_event = threading.Event()

        if TTS_ENGINE == "vieneu" and VIENEU_PRELOAD:
            threading.Thread(target=self._preload_vieneu, daemon=True).start()

    def _preload_vieneu(self):
        t0 = time.perf_counter()
        try:
            self._get_vieneu()
            print(f"[VIENEU] model ready in {time.perf_counter() - t0:.3f}s")
        except Exception as e:
            # Không làm Buddy chết khi package/model chưa sẵn sàng; lượt nói sẽ tự fallback.
            print("[VIENEU PRELOAD ERROR]", e)

    def _get_vieneu(self):
        if self._vieneu is not None:
            return self._vieneu

        with self._vieneu_lock:
            if self._vieneu is not None:
                return self._vieneu

            from vieneu import Vieneu

            backend = str(VIENEU_BACKEND or "auto").strip().lower()
            if backend in {"", "auto"}:
                self._vieneu = Vieneu()
            else:
                self._vieneu = Vieneu(backend=backend)

            return self._vieneu

    def dung(self):
        """Cho phép dừng TTS streaming (chuẩn bị cho barge-in)."""
        self._stop_event.set()

    def noi(self, text, on_done=None):
        self._stop_event.clear()
        threading.Thread(
            target=self._tien_trinh,
            args=(text, on_done),
            daemon=True,
        ).start()

    def _tien_trinh(self, text, on_done):
        try:
            # Khóa riêng của dịch vụ + khóa dùng chung toàn tiến trình:
            # không để TTS chồng lấn STT hay hai lượt TTS chồng nhau.
            with self.lock:
                with audio_lock:
                    self._noi_voi_fallback(text)
        finally:
            sau_dau_ra_giai_phong()
            if on_done:
                on_done()

    def _noi_voi_fallback(self, text):
        # VieNeu-only mode: consistent Mai Anh voice; NEVER switch to Edge/pyttsx3.
        if TTS_ENGINE == "vieneu":
            try:
                self._vieneu_stream(text)
                return
            except VieNeuStreamError as e:
                print("[VIENEU TTS ERROR]", e)
                print("[VIENEU ONLY] TTS stopped; no other voice will be used")
                return
            except Exception as e:
                print("[VIENEU TTS ERROR]", e)
                print("[VIENEU ONLY] TTS stopped; no other voice will be used")
                return

        # Other explicitly selected engines retain their original behavior.
        if TTS_EDGE_FALLBACK:
            try:
                print("[TTS] Edge TTS")
                self._edge(text)
                return
            except Exception as e:
                print("[EDGE TTS ERROR]", e)

        if TTS_PYTTSX3_FALLBACK:
            print("[TTS] pyttsx3")
            self._pyttsx3(text)
            return

        raise RuntimeError("No TTS backend succeeded")

    def _vieneu_stream(self, text):
        """Sinh + phát VieNeu v3 Turbo theo luồng.

        Producer: infer_stream() -> queue các chunk np.float32 @ 48 kHz.
        Consumer: prebuffer VIENEU_START_BUFFER_MS rồi ghi liên tục vào
        sounddevice.OutputStream. Không chờ toàn bộ câu sinh xong.
        """
        import sounddevice as sd

        settings = tai_cai_dat()
        voice = settings.get("vieneu_voice") or VIENEU_VOICE
        start_buffer_ms = int(VIENEU_START_BUFFER_MS)  # use config/env default 450ms, not stale user settings
        # user_settings.json may still contain the old 2-second timeout.
        # Never abort VieNeu prematurely: the first audio can arrive just after 2s.
        first_audio_timeout = max(
            10.0,
            float(settings.get("vieneu_first_audio_timeout", VIENEU_FIRST_AUDIO_TIMEOUT)),
        )
        stream_stall_timeout = float(settings.get("vieneu_stream_stall_timeout", VIENEU_STREAM_STALL_TIMEOUT))
        output_device = settings.get("audio_output_device")
        output_blocksize = int(settings.get("vieneu_output_blocksize", 2048))

        t0 = time.perf_counter()
        print(
            f"[VIENEU TIMING] request start: voice={voice}, "
            f"chars={len(text)}, backend={VIENEU_BACKEND}, "
            f"buffer={start_buffer_ms}ms, output={output_device if output_device is not None else 'default'}"
        )

        try:
            model = self._get_vieneu()
        except Exception as e:
            raise VieNeuStreamError(f"model load failed: {e}", played_audio=False) from e

        audio_q = queue.Queue(maxsize=128)
        producer_done = threading.Event()
        producer_error = []
        first_chunk_time = []
        sentinel = object()

        def producer():
            try:
                for chunk in model.infer_stream(text, voice=voice):
                    if self._stop_event.is_set():
                        break
                    arr = np.asarray(chunk, dtype=np.float32).reshape(-1)
                    if arr.size == 0:
                        continue
                    if not first_chunk_time:
                        first_chunk_time.append(time.perf_counter())
                        print(
                            f"[VIENEU TIMING] first generated chunk: "
                            f"{first_chunk_time[0] - t0:.3f}s"
                        )
                    audio_q.put(arr)
            except Exception as e:
                producer_error.append(e)
            finally:
                producer_done.set()
                try:
                    audio_q.put_nowait(sentinel)
                except queue.Full:
                    pass

        threading.Thread(target=producer, daemon=True).start()

        start_samples = max(
            1,
            int(VIENEU_SAMPLE_RATE * max(0, start_buffer_ms) / 1000.0),
        )
        pending = []
        buffered_samples = 0
        max_buffered_samples = 0
        played_audio = False
        synthesis_end_logged = False

        # Chờ chunk đầu tiên tối đa N giây. Nếu chưa phát gì thì có thể fallback sạch sẽ.
        try:
            item = audio_q.get(timeout=first_audio_timeout)
        except queue.Empty as e:
            raise VieNeuStreamError(
                f"first audio timeout after {first_audio_timeout:.2f}s",
                played_audio=False,
            ) from e

        if item is sentinel:
            if producer_error:
                raise VieNeuStreamError(
                    f"stream failed before audio: {producer_error[0]}",
                    played_audio=False,
                )
            raise VieNeuStreamError("stream ended before audio", played_audio=False)

        pending.append(item)
        buffered_samples += item.size

        # Prebuffer một lượng nhỏ để hạn chế underrun ở đầu câu.
        buffer_deadline = time.perf_counter() + max(
            stream_stall_timeout,
            first_audio_timeout,
        )
        stream_ended_while_buffering = False

        while buffered_samples < start_samples and not self._stop_event.is_set():
            remaining = buffer_deadline - time.perf_counter()
            if remaining <= 0:
                # Đã có audio, ưu tiên bắt đầu phát thay vì đợi vô hạn.
                break
            try:
                item = audio_q.get(timeout=min(0.10, remaining))
            except queue.Empty:
                if producer_done.is_set():
                    break
                continue

            if item is sentinel:
                stream_ended_while_buffering = True
                break

            pending.append(item)
            buffered_samples += item.size

        t_buffer = time.perf_counter()
        print(
            f"[VIENEU TIMING] startup buffer ready: {t_buffer - t0:.3f}s "
            f"({buffered_samples / VIENEU_SAMPLE_RATE * 1000.0:.0f} ms audio)"
        )

        if buffered_samples <= 0:
            err = producer_error[0] if producer_error else "no buffered audio"
            raise VieNeuStreamError(str(err), played_audio=False)

        try:
            # VieNeu Turbo sinh native 48 kHz float32. Dùng default output device của Ubuntu.
            stream_kwargs = dict(
                samplerate=VIENEU_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=output_blocksize,
            )
            if output_device is not None:
                stream_kwargs["device"] = int(output_device)
            with sd.OutputStream(**stream_kwargs) as stream:
                t_play_start = time.perf_counter()
                played_audio = True
                print(
                    f"[VIENEU TIMING] playback start: {t_play_start - t0:.3f}s "
                    f"(startup target={start_buffer_ms}ms)"
                )

                # Phát phần prebuffer trước.
                for arr in pending:
                    if self._stop_event.is_set():
                        break
                    stream.write(arr.reshape(-1, 1))

                pending.clear()
                buffered_samples = 0

                # Sau đó vừa nhận vừa phát. OutputStream.write() là blocking nên tự tạo backpressure;
                # producer vẫn chạy độc lập và queue hấp thụ jitter ngắn.
                if not stream_ended_while_buffering:
                    while not self._stop_event.is_set():
                        try:
                            item = audio_q.get(timeout=stream_stall_timeout)
                        except queue.Empty as e:
                            if producer_done.is_set():
                                break
                            raise VieNeuStreamError(
                                f"stream stalled > {stream_stall_timeout:.2f}s",
                                played_audio=True,
                            ) from e

                        if item is sentinel:
                            break

                        # Xấp xỉ mức buffer nằm trong queue để debug.
                        try:
                            queued_samples = sum(
                                x.size for x in list(audio_q.queue)
                                if isinstance(x, np.ndarray)
                            )
                            max_buffered_samples = max(max_buffered_samples, queued_samples)
                        except Exception:
                            pass

                        stream.write(item.reshape(-1, 1))

                if producer_done.is_set() and not synthesis_end_logged:
                    synthesis_end_logged = True
                    print(
                        f"[VIENEU TIMING] synthesis end: "
                        f"{time.perf_counter() - t0:.3f}s"
                    )

                # write() đã block đến khi buffer PortAudio nhận xong; stop()/context manager
                # chờ phần còn lại phát nốt trước khi đóng stream.
                stream.stop()

            t_play_end = time.perf_counter()
            print(
                f"[VIENEU TIMING] playback end: {t_play_end - t0:.3f}s "
                f"(play duration {t_play_end - t_play_start:.3f}s)"
            )
            print(
                f"[VIENEU BUFFER] startup={start_buffer_ms}ms, blocksize={output_blocksize}, "
                f"max_queued≈{max_buffered_samples / VIENEU_SAMPLE_RATE * 1000.0:.0f}ms"
            )

        except VieNeuStreamError:
            raise
        except Exception as e:
            raise VieNeuStreamError(str(e), played_audio=played_audio) from e

        if producer_error:
            raise VieNeuStreamError(
                f"producer failed: {producer_error[0]}",
                played_audio=played_audio,
            )

    def _edge(self, text):
        """Fallback Edge TTS: giữ log timing để chẩn đoán mạng."""
        import edge_tts
        import pygame

        f = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        name = f.name
        f.close()

        async def sinh_co_log():
            communicate = edge_tts.Communicate(
                text=text,
                voice=EDGE_TTS_VOICE,
                rate=EDGE_TTS_RATE,
            )

            first_audio_logged = False
            with open(name, "wb") as audio_file:
                async for chunk in communicate.stream():
                    if chunk.get("type") != "audio":
                        continue
                    if not first_audio_logged:
                        t_first = time.perf_counter()
                        print(
                            f"[TTS TIMING] first audio received: "
                            f"{t_first - t0:.3f}s after Edge call"
                        )
                        first_audio_logged = True
                    audio_file.write(chunk["data"])

            if not first_audio_logged:
                raise RuntimeError("Edge TTS returned no audio data")

        try:
            t0 = time.perf_counter()
            print(
                f"[TTS TIMING] Edge call start: "
                f"voice={EDGE_TTS_VOICE}, chars={len(text)}"
            )

            asyncio.run(sinh_co_log())
            t_file_done = time.perf_counter()
            print(
                f"[TTS TIMING] file complete: "
                f"{t_file_done - t0:.3f}s after Edge call"
            )

            if pygame.mixer.get_init():
                try:
                    pygame.mixer.quit()
                except Exception:
                    pass

            pygame.mixer.init()
            self._pygame = pygame
            pygame.mixer.music.load(name)
            pygame.mixer.music.play()
            t_play_start = time.perf_counter()
            print(
                f"[TTS TIMING] playback start: "
                f"{t_play_start - t0:.3f}s after Edge call "
                f"(+{t_play_start - t_file_done:.3f}s after file complete)"
            )

            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(20)

            t_play_end = time.perf_counter()
            print(
                f"[TTS TIMING] playback end: "
                f"{t_play_end - t0:.3f}s after Edge call "
                f"(play duration {t_play_end - t_play_start:.3f}s)"
            )

            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass

        finally:
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.quit()
            except Exception as e:
                print("[AUDIO MIXER QUIT WARN]", e)

            self._pygame = None
            try:
                os.remove(name)
            except Exception:
                pass

    def _pyttsx3(self, text):
        import pyttsx3

        e = pyttsx3.init()
        e.setProperty("rate", 155)

        for v in e.getProperty("voices"):
            blob = (
                str(v.id)
                + str(v.name)
                + str(getattr(v, "languages", ""))
            ).lower()
            if "vietnam" in blob or "vi-vn" in blob:
                e.setProperty("voice", v.id)
                break

        try:
            e.say(text)
            e.runAndWait()
        finally:
            try:
                e.stop()
            except Exception:
                pass
            del e
