import json
import re
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from cau_hinh import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT, APP_TIMEZONE
from dich_vu.trich_xuat_thong_tin import trich_xuat_thong_tin_nhiem_vu, chuan_hoa_lich_loai


CHAT_SYSTEM = """
Bạn là OneStep Buddy, một huấn luyện viên nhận thức AI đồng hành trên bàn học.

DANH TÍNH
- Tên của bạn là OneStep Buddy.
- Bạn là trợ lý AI hỗ trợ người dùng nhớ việc, bắt đầu việc, quản lý thời gian,
  luyện khả năng tự nhớ và kiểm tra một số đồ vật bằng camera khi hệ thống xác nhận.
- Bạn không phải bác sĩ và không phải công cụ chẩn đoán ADHD.

CÁCH NÓI
- Luôn trả lời bằng tiếng Việt tự nhiên.
- Xưng "mình", gọi người dùng là "bạn".
- Thân thiện, ngắn, rõ. Thông thường 1-3 câu.
- Nếu câu hỏi đơn giản, trả lời đơn giản.
- Nếu câu hỏi mơ hồ, hỏi lại ngắn gọn thay vì tự suy đoán.
- Không dùng tiếng Trung/chữ Hán.

NGUYÊN TẮC HÀNH ĐỘNG
- Ưu tiên một bước nhỏ có thể làm ngay.
- Task đơn giản không tự chia thành checklist dài.
- Chỉ chia nhỏ khi người dùng yêu cầu hoặc nói họ không biết bắt đầu từ đâu.
- Không giả vờ đã tạo, sửa, xóa, hoàn thành task nếu backend chưa xác nhận.
- Không giả vờ đã điều khiển phần cứng.
- Không nói đã nhìn thấy đồ vật nếu DichVuThiGiac chưa xác nhận.
- Nếu chưa có dữ liệu về vị trí đồ vật, nói rõ là chưa có dữ liệu; không đoán.

AN TOÀN
- Không chẩn đoán hoặc điều trị ADHD.
- Không đưa lời khuyên y khoa thay chuyên gia.
- OneStep chỉ hỗ trợ tự quản lý nhiệm vụ, thời gian, routine và khả năng tự nhớ.

KHI NGƯỜI DÙNG HỎI VỀ BẠN
- "Bạn là ai?", "Bạn là gì?", "Bạn tên gì?" hoặc câu tương tự:
  trả lời tự nhiên rằng bạn là OneStep Buddy và nêu vai trò ngắn gọn.
- "Bạn làm được gì?", "Bạn giúp được gì?" hoặc câu tương tự:
  chỉ nói các khả năng thực sự của hệ thống.
"""


COMMAND_SYSTEM = """
Bạn là bộ phân tích ý định tiếng Việt của OneStep Buddy.
Nhiệm vụ duy nhất: đọc câu người dùng và trả về MỘT JSON object hợp lệ.
Không markdown, không giải thích, không thêm chữ ngoài JSON.

INTENT HỢP LỆ
- create_task: tạo một task mới.
- coach_task: người dùng muốn được chia nhỏ/bắt đầu một việc.
- start_task: bắt đầu task hiện tại.
- complete_task: đã làm xong task/bước hiện tại.
- snooze_task: hoãn/nhắc lại sau.
- cancel_task: hủy task/lịch hiện tại.
- query_current_task: hỏi đang có việc gì / việc tiếp theo là gì.
- coaching_progress: hỏi tiến trình/routine/mức hỗ trợ.
- check_items: dùng camera kiểm tra có/thiếu những đồ nào.
- find_object: hỏi một đồ vật đang/đã ở đâu.
- show_last_image: muốn xem lại ảnh vision gần nhất.
- show_image_longer: muốn giữ ảnh vision lâu hơn.
- identity: hỏi OneStep Buddy là ai/là gì/tên gì.
- capability: hỏi OneStep Buddy làm được gì/có thể giúp gì.
- chat: hội thoại hoặc câu hỏi không thuộc các intent trên.

SCHEMA BẮT BUỘC
{
  "intent": "chat",
  "title": null,
  "schedule_type": null,
  "scheduled_at": null,
  "scheduled_time": null,
  "repeat_days": [],
  "snooze_minutes": 5,
  "estimated_minutes": null,
  "deadline_at": null,
  "required_items": [],
  "object_name": null,
  "confidence": 0.0
}

QUY TẮC QUAN TRỌNG
1. Không ép mọi câu vào task.
2. Nếu không có thời gian task thật sự trong câu, scheduled_at PHẢI là null.
3. Không tự điền thời gian hiện tại vào scheduled_at.
4. null phải là JSON null, KHÔNG phải chuỗi "null".
5. Nếu không có schedule_type, trả null.
6. Nếu người dùng chỉ trò chuyện, hỏi kiến thức, hỏi danh tính, hỏi khả năng -> không tạo task.

PHÂN LOẠI
- "bạn là ai", "bạn là gì", "bạn tên gì", "mày là ai", câu tương đương -> identity.
- "xin chào", "chào bạn", "hello", "hi" -> chat, KHÔNG phải identity.
- "bạn làm được gì", "bạn có thể giúp gì", "chức năng của bạn là gì", câu tương đương -> capability.
- "không biết bắt đầu", "chia nhỏ", "giúp mình bắt đầu" -> coach_task.
- "bắt đầu đi", "mình bắt đầu nhé" khi nói task hiện tại -> start_task.
- "xong rồi", "mình làm xong rồi", "hoàn thành rồi" -> complete_task.
- "nhắc lại sau", "hoãn 5 phút", "để lát nữa" -> snooze_task.
- "hủy việc này", "bỏ lịch này" -> cancel_task.
- "mình có việc gì", "việc tiếp theo là gì", "giờ mình cần làm gì" -> query_current_task.
- "mình tiến bộ thế nào", "mức hỗ trợ của mình", "routine thế nào" -> coaching_progress.
- "kiểm tra đồ", "còn thiếu gì", "nhìn xem có cặp sách bình nước chưa" -> check_items.
- "cặp của tôi ở đâu", "điện thoại đâu rồi", "tìm bình nước giúp mình" -> find_object.
- "cho mình xem lại hình", "hiện lại ảnh vừa rồi" -> show_last_image.
- "cho mình xem lâu hơn", "giữ hình lâu hơn" -> show_image_longer.

THỜI GIAN
- Chỉ parse thời gian nếu câu thật sự nói về một task/lịch.
- Ví dụ "Nhắc mình uống nước lúc 15:30" -> create_task, scheduled_at có giá trị.
- Ví dụ "7:20 mình phải đi học, chuẩn bị mất 10 phút" -> create_task,
  deadline_at=07:20, estimated_minutes=10.
- Câu "bạn là ai" -> identity và mọi trường thời gian đều null.

CONFIDENCE
- 0.90-1.00: rất chắc.
- 0.70-0.89: khá chắc.
- 0.50-0.69: còn mơ hồ.
- dưới 0.50: ưu tiên chat.
"""


PLAN_SYSTEM = """
Bạn chia một nhiệm vụ thành 1 đến 5 bước hành động rất nhỏ, cụ thể, dễ bắt đầu.
Chỉ trả JSON: {"steps":["...","..."]}.
Không giải bài/học thay người dùng.
Bước đầu tiên phải có thể thực hiện ngay trong khoảng 1-2 phút.
Nếu nhiệm vụ vốn đã ngắn và rõ, trả đúng 1 bước.
"""


def chua_tieng_trung(text):
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def lam_sach_nhiem_vu_tieu_de(title):
    if not title:
        return title
    title = str(title).strip()
    low = title.lower()
    for prefix in ["tôi sẽ ", "mình sẽ ", "tôi ", "mình ", "sẽ "]:
        if low.startswith(prefix):
            title = title[len(prefix):].strip()
            break
    return title[:1].upper() + title[1:] if title else title


def _rong_neu_null_chuoi(value):
    if isinstance(value, str) and value.strip().lower() in {"null", "none", ""}:
        return None
    return value


class DichVuAI:
    def _ollama(self, messages, temperature=0.2, timeout=None, num_predict=220):
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",
            "options": {
                "temperature": temperature,
                "top_p": 0.9,
                "num_predict": num_predict,
            },
        }
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=timeout or OLLAMA_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return data["message"]["content"].strip()

    def _json(self, raw):
        raw = (raw or "").replace("```json", "").replace("```", "").strip()
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group(0) if m else raw)

    def lap_ke_hoach_nhiem_vu(self, title):
        try:
            d = self._json(self._ollama(
                [
                    {"role": "system", "content": PLAN_SYSTEM},
                    {"role": "user", "content": title},
                ],
                temperature=0.0,
                timeout=OLLAMA_TIMEOUT,
                num_predict=180,
            ))
            steps = [str(x).strip() for x in d.get("steps", []) if str(x).strip()][:5]
            return steps or [title]
        except Exception as e:
            print("[TASK PLAN ERROR]", e)
            return [title]

    def phan_tich_lenh(self, text):
        try:
            now = datetime.now(ZoneInfo(APP_TIMEZONE))
        except Exception:
            now = datetime.now()

        time_context = (
            f"Thời gian hiện tại: {now.isoformat(timespec='minutes')}. "
            f"Ngày hiện tại: {now:%Y-%m-%d}. "
            f"Múi giờ ứng dụng: {APP_TIMEZONE}."
        )

        default = {
            "intent": "chat",
            "title": None,
            "schedule_type": None,
            "scheduled_at": None,
            "scheduled_time": None,
            "repeat_days": [],
            "snooze_minutes": 5,
            "estimated_minutes": None,
            "deadline_at": None,
            "required_items": [],
            "object_name": None,
            "confidence": 0.0,
        }

        try:
            raw = self._ollama(
                [
                    {"role": "system", "content": COMMAND_SYSTEM},
                    {"role": "system", "content": time_context},
                    {"role": "user", "content": text},
                ],
                temperature=0.0,
                timeout=OLLAMA_TIMEOUT,
                num_predict=240,
            )
            d = self._json(raw)
        except Exception as e:
            print("[COMMAND PARSE ERROR]", e)
            return default

        out = dict(default)
        for k in out:
            if k in d:
                out[k] = d[k]

        # Chuẩn hóa các lỗi JSON thường gặp từ mô hình nhỏ.
        for k in ["title", "schedule_type", "scheduled_at", "scheduled_time",
                  "deadline_at", "object_name"]:
            out[k] = _rong_neu_null_chuoi(out[k])
        out["schedule_type"] = chuan_hoa_lich_loai(out.get("schedule_type"))

        valid_intents = {
            "create_task", "coach_task", "start_task", "complete_task",
            "snooze_task", "cancel_task", "query_current_task",
            "coaching_progress", "check_items", "find_object",
            "show_last_image", "show_image_longer",
            "identity", "capability", "chat",
        }
        if out["intent"] not in valid_intents:
            out["intent"] = "chat"
            out["confidence"] = 0.0

        # Chuẩn hóa an toàn: intent không phải nhiệm vụ không được tự tạo dữ liệu lịch.
        if out["intent"] in {
            "identity", "capability", "chat", "find_object",
            "check_items", "show_last_image", "show_image_longer",
            "coaching_progress", "query_current_task",
        }:
            out["scheduled_at"] = None
            out["scheduled_time"] = None
            out["deadline_at"] = None
            out["estimated_minutes"] = None
            out["schedule_type"] = None

        # v9.7: Qwen3B xác định intent; Python trích xuất tiêu đề / giờ / ngày / lặp lại.
        if out["intent"] in {"create_task", "coach_task"}:
            slots = trich_xuat_thong_tin_nhiem_vu(text, tz_name=APP_TIMEZONE)
            for k in ["title","schedule_type","scheduled_at","scheduled_time","repeat_days","estimated_minutes"]:
                v = slots.get(k)
                if v not in (None, [], ""):
                    out[k] = v
        elif out["intent"] == "snooze_task":
            slots = trich_xuat_thong_tin_nhiem_vu(text, tz_name=APP_TIMEZONE)
            if slots.get("snooze_minutes"):
                out["snooze_minutes"] = slots["snooze_minutes"]

        try:
            out["confidence"] = max(0.0, min(float(out.get("confidence") or 0.0), 1.0))
        except Exception:
            out["confidence"] = 0.0

        try:
            out["snooze_minutes"] = max(1, min(int(out.get("snooze_minutes") or 5), 120))
        except Exception:
            out["snooze_minutes"] = 5

        if not isinstance(out.get("repeat_days"), list):
            out["repeat_days"] = []
        if not isinstance(out.get("required_items"), list):
            out["required_items"] = []

        if out.get("title"):
            out["title"] = lam_sach_nhiem_vu_tieu_de(out["title"])

        return out

    def hoi_thoai(self, text, context=""):
        messages = [
            {"role": "system", "content": CHAT_SYSTEM},
        ]
        if context:
            messages.append({
                "role": "system",
                "content": "Ngữ cảnh backend hiện tại, chỉ dùng khi liên quan:\n" + context,
            })
        messages.append({"role": "user", "content": text})

        try:
            reply = self._ollama(
                messages,
                temperature=0.25,
                timeout=OLLAMA_TIMEOUT,
                num_predict=180,
            )
            if chua_tieng_trung(reply):
                reply = self._ollama(
                    [
                        {"role": "system", "content": CHAT_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                "Viết lại câu trả lời sau hoàn toàn bằng tiếng Việt tự nhiên, "
                                "không dùng chữ Hán:\n" + reply
                            ),
                        },
                    ],
                    temperature=0.1,
                    timeout=OLLAMA_TIMEOUT,
                    num_predict=180,
                )
            return reply.strip(), f"ollama:{OLLAMA_MODEL}"
        except Exception as e:
            print("[CHAT ERROR]", e)
            return "Mình đang gặp lỗi kết nối AI. Bạn thử lại một chút nhé.", "fallback"
