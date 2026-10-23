PATCH: ADHD-OneStep-main -> Settings + Help Prompt CRUD

Cach cap nhat:
1. Sao luu source hien tai.
2. Giai nen patch vao thu muc goc ADHD-OneStep-main.
3. Cho phep ghi de cac file trung ten.
4. KHONG xoa storage/, models/, data/ cua source hien tai.

Patch nay KHONG chua:
- storage/onestep.db
- models/*.joblib
- data training CSV/JSONL
- notebook training
Do do se khong ghi de du lieu/model hien tai.

Noi dung cap nhat:
- Settings UI: mic, audio output, camera, VieNeu buffer va cac tham so lien quan.
- Help UI: danh sach prompt theo tinh huong.
- Them/Sua/Xoa prompt.
- Luu help_prompts vao storage/user_settings.json.
- Settings va Help dung chung JSON theo co che merge, khong ghi de du lieu cua nhau.
- F2 mo Settings, F3 mo Help.
- Giu cac cap nhat Face/Chat, keyboard, shortcut, TTS streaming hien tai.
