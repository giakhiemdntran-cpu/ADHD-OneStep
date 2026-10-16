#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Arduino_GFX_Library.h>
#include <Wire.h>




const char* WIFI_SSID     = "YOUR_WIFI";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";
const char* SERVER        = "http:
const char* DEVICE_ID     = "oneband01";


const unsigned long POLL_MS = 1800;


#define LCD_BL    2
#define LCD_DC    8
#define LCD_CS    9
#define LCD_SCK   10
#define LCD_MOSI  11
#define LCD_MISO  12
#define LCD_RST   14

#define TP_INT    5
#define TP_SDA    6
#define TP_SCL    7
#define TP_RST    13


#define VIB_PIN   4

#define CST816_ADDR 0x15

Arduino_DataBus *bus = new Arduino_ESP32SPI(
  LCD_DC, LCD_CS, LCD_SCK, LCD_MOSI, LCD_MISO
);
Arduino_GFX *gfx = new Arduino_GC9A01(
  bus, LCD_RST, 0, true
);


#define C_BG       0xEF7D
#define C_CARD     0xFFFF
#define C_INK      0x2186
#define C_MUTED    0x6B6D
#define C_PRIMARY  0x3C10
#define C_BLUE     0x4D7F
#define C_ORANGE   0xFD20
#define C_RED      0xD9A7
#define C_GREEN    0x55ED
#define C_DARK     0x18E3
#define C_YELLOW   0xFEC0

enum Screen {
  HOME,
  TASK_VIEW,
  FOCUS_VIEW,
  WATER_VIEW,
  STATUS_VIEW,
  MEMORY2_VIEW,
  MEMORY1_VIEW,
  MEMORY0_VIEW,
  RESULT_VIEW
};

Screen screen = HOME;


unsigned long lastPoll = 0;
unsigned long lastTouch = 0;
unsigned long focusLastTick = 0;

bool hasTask = false;
String taskTitle = "";
String taskStep = "";
String taskTime = "";
int promptLevel = -1;

int currentNotificationId = -1;
int lastBuzzedNotificationId = -1;
String notificationType = "";
String notificationTitle = "";
String notificationHint = "";

bool focusRunning = false;
int focusSeconds = 25 * 60;
int waterCount = 0;


void clearScreen(uint16_t color = C_BG) {
  gfx->fillScreen(color);
}

String shortText(String s, int n) {
  if ((int)s.length() <= n) return s;
  return s.substring(0, n - 2) + "..";
}

void centerText(const String &txt, int y, int size, uint16_t color) {
  gfx->setTextSize(size);
  gfx->setTextColor(color);
  gfx->setTextWrap(false);

  int16_t x1, y1;
  uint16_t w, h;
  gfx->getTextBounds(txt, 0, y, &x1, &y1, &w, &h);

  int x = (240 - w) / 2;
  if (x < 4) x = 4;
  gfx->setCursor(x, y);
  gfx->print(txt);
}

void drawButton(
  int x, int y, int w, int h,
  uint16_t color,
  const String &label,
  int textSize = 1
) {
  gfx->fillRoundRect(x, y, w, h, 15, color);
  gfx->drawRoundRect(x, y, w, h, 15, C_CARD);

  gfx->setTextColor(C_CARD);
  gfx->setTextSize(textSize);

  int16_t x1, y1;
  uint16_t tw, th;
  gfx->getTextBounds(label, 0, 0, &x1, &y1, &tw, &th);

  gfx->setCursor(
    x + (w - tw) / 2,
    y + (h - th) / 2
  );
  gfx->print(label);
}

// Nút BACK đã làm lớn hơn và đưa sâu vào trong như yêu cầu trước.
void drawBack() {
  gfx->fillCircle(38, 36, 25, C_CARD);
  gfx->drawCircle(38, 36, 25, C_MUTED);

  gfx->setTextColor(C_INK);
  gfx->setTextSize(3);
  gfx->setCursor(27, 24);
  gfx->print("<");
}

void drawPromptBadge() {
  if (promptLevel < 0) return;
  gfx->fillRoundRect(164, 18, 48, 22, 10, C_DARK);
  gfx->setTextColor(C_CARD);
  gfx->setTextSize(1);
  gfx->setCursor(176, 25);
  gfx->print("L");
  gfx->print(promptLevel);
}


void drawHome() {
  screen = HOME;
  clearScreen();

  centerText("OneStep", 16, 2, C_INK);
  drawPromptBadge();

  gfx->fillRoundRect(28, 47, 184, 62, 20, C_CARD);
  gfx->setTextColor(C_MUTED);
  gfx->setTextSize(1);
  gfx->setCursor(44, 59);
  gfx->print(hasTask ? "TIEP THEO" : "HOM NAY");

  gfx->setTextColor(C_INK);
  gfx->setTextSize(2);
  gfx->setCursor(44, 78);
  gfx->print(hasTask ? shortText(taskTitle, 15) : "Thong thoang!");

  drawButton(30, 124, 82, 42, C_PRIMARY, "TASK");
  drawButton(128, 124, 82, 42, C_BLUE, "FOCUS");
  drawButton(30, 176, 82, 42, C_ORANGE, "NUOC");
  drawButton(128, 176, 82, 42, C_DARK, "WIFI");
}

void drawTaskView() {
  screen = TASK_VIEW;
  clearScreen();
  drawBack();
  centerText("Nhiem vu", 18, 2, C_INK);

  if (!hasTask) {
    gfx->fillRoundRect(30, 70, 180, 96, 22, C_CARD);
    centerText("Chua co task", 92, 2, C_INK);
    centerText("Buddy chua gui", 120, 1, C_MUTED);
    centerText("nhiem vu nao.", 135, 1, C_MUTED);
    drawButton(54, 180, 132, 40, C_PRIMARY, "VE HOME");
    return;
  }

  gfx->fillRoundRect(28, 58, 184, 116, 22, C_CARD);

  gfx->setTextColor(C_INK);
  gfx->setTextSize(2);
  gfx->setCursor(44, 74);
  gfx->print(shortText(taskTitle, 15));

  gfx->setTextColor(C_MUTED);
  gfx->setTextSize(1);
  gfx->setCursor(44, 108);
  gfx->print(shortText(taskStep, 25));

  gfx->setCursor(44, 136);
  gfx->print(taskTime);

  drawButton(54, 184, 132, 38, C_PRIMARY, "VE HOME");
}

void drawFocusView() {
  screen = FOCUS_VIEW;
  clearScreen();
  drawBack();
  centerText("Focus", 20, 2, C_INK);

  int mm = focusSeconds / 60;
  int ss = focusSeconds % 60;
  char buf[8];
  sprintf(buf, "%02d:%02d", mm, ss);

  centerText(String(buf), 82, 4, C_INK);

  drawButton(
    62, 160, 116, 42,
    focusRunning ? C_RED : C_PRIMARY,
    focusRunning ? "TAM DUNG" : "BAT DAU"
  );
}

void drawWaterView() {
  screen = WATER_VIEW;
  clearScreen();
  drawBack();
  centerText("Uong nuoc", 18, 2, C_INK);

  gfx->fillCircle(120, 110, 55, C_BLUE);
  centerText(String(waterCount), 90, 4, C_CARD);
  centerText("ly hom nay", 130, 1, C_CARD);

  drawButton(62, 178, 116, 40, C_PRIMARY, "+ 1 LY");
}

void drawStatusView() {
  screen = STATUS_VIEW;
  clearScreen();
  drawBack();
  centerText("Trang thai", 18, 2, C_INK);

  gfx->fillRoundRect(28, 62, 184, 116, 22, C_CARD);
  gfx->setTextColor(C_INK);
  gfx->setTextSize(1);

  gfx->setCursor(46, 80);
  gfx->print("WiFi: ");
  gfx->print(WiFi.status() == WL_CONNECTED ? "OK" : "MAT");

  gfx->setCursor(46, 105);
  gfx->print("IP: ");
  gfx->print(WiFi.localIP());

  gfx->setCursor(46, 130);
  gfx->print("Task: ");
  gfx->print(hasTask ? "CO" : "KHONG");

  gfx->setCursor(46, 153);
  gfx->print("Memory level: ");
  if (promptLevel >= 0) gfx->print(promptLevel);
  else gfx->print("-");

  drawButton(62, 188, 116, 34, C_DARK, "LAM MOI");
}





void drawMemory2() {
  screen = MEMORY2_VIEW;
  clearScreen(C_CARD);

  gfx->fillCircle(120, 36, 21, C_ORANGE);
  centerText("2", 25, 2, C_CARD);

  centerText("BAN CO NHO?", 64, 2, C_INK);
  centerText(shortText(notificationTitle, 18), 96, 2, C_INK);
  centerText("Hay chon mot cau tra loi", 130, 1, C_MUTED);


  drawButton(10, 172, 68, 44, C_BLUE, "NHO");
  drawButton(86, 172, 68, 44, C_GREEN, "XONG");
  drawButton(162, 172, 68, 44, C_RED, "KHONG");
}



void drawMemory1() {
  screen = MEMORY1_VIEW;
  clearScreen(C_CARD);

  gfx->fillCircle(120, 36, 21, C_BLUE);
  centerText("1", 25, 2, C_CARD);

  centerText("BAN CO 1 VIEC", 70, 2, C_INK);
  centerText("CAN LAM", 98, 2, C_INK);
  centerText("Ban co nho viec gi khong?", 133, 1, C_MUTED);

  drawButton(26, 174, 88, 44, C_GREEN, "NHO");
  drawButton(126, 174, 88, 44, C_RED, "KHONG");
}



void drawMemory0() {
  screen = MEMORY0_VIEW;
  clearScreen(C_CARD);

  gfx->fillCircle(120, 36, 21, C_GREEN);
  centerText("0", 25, 2, C_CARD);

  centerText("LUC NAY...", 66, 2, C_INK);
  centerText("BAN DA LAM CHUA?", 96, 2, C_INK);
  centerText("Tu nho truoc khi xem goi y", 128, 1, C_MUTED);

  drawButton(10, 171, 68, 46, C_GREEN, "XONG");
  drawButton(86, 171, 68, 46, C_BLUE, "NHO");
  drawButton(162, 171, 68, 46, C_RED, "KHONG");
}

void drawResult(const String &line1, const String &line2 = "") {
  screen = RESULT_VIEW;
  clearScreen();

  gfx->fillCircle(120, 55, 28, C_GREEN);
  centerText("OK", 45, 2, C_CARD);

  centerText(shortText(line1, 26), 105, 1, C_INK);
  if (line2.length()) {
    centerText(shortText(line2, 26), 128, 1, C_MUTED);
  }

  drawButton(54, 176, 132, 42, C_PRIMARY, "VE HOME");
}


void touchReset() {
  pinMode(TP_RST, OUTPUT);
  digitalWrite(TP_RST, LOW);
  delay(10);
  digitalWrite(TP_RST, HIGH);
  delay(50);
}

bool readTouch(int &x, int &y) {
  Wire.beginTransmission(CST816_ADDR);
  Wire.write(0x02);

  if (Wire.endTransmission(false) != 0) return false;

  Wire.requestFrom(CST816_ADDR, 5);
  if (Wire.available() < 5) return false;

  uint8_t fingers = Wire.read();
  uint8_t xh = Wire.read();
  uint8_t xl = Wire.read();
  uint8_t yh = Wire.read();
  uint8_t yl = Wire.read();

  if (fingers == 0) return false;

  x = ((xh & 0x0F) << 8) | xl;
  y = ((yh & 0x0F) << 8) | yl;

  // Nếu touch bị đảo trên board của bạn, bật 1 hoặc 2 dòng:



  return x >= 0 && x < 240 && y >= 0 && y < 240;
}

bool inside(int x, int y, int x1, int y1, int x2, int y2) {
  return x >= x1 && x <= x2 && y >= y1 && y <= y2;
}


void tapHaptic() {
  digitalWrite(VIB_PIN, HIGH);
  delay(45);
  digitalWrite(VIB_PIN, LOW);
}

void vibrateLevel2() {
  // Rõ hơn: 2 nhịp
  digitalWrite(VIB_PIN, HIGH); delay(180);
  digitalWrite(VIB_PIN, LOW);  delay(100);
  digitalWrite(VIB_PIN, HIGH); delay(240);
  digitalWrite(VIB_PIN, LOW);
}

void vibrateLevel1() {
  // Gợi ý nhẹ: 1 nhịp
  digitalWrite(VIB_PIN, HIGH); delay(140);
  digitalWrite(VIB_PIN, LOW);
}

void vibrateLevel0Check() {
  // Self-check: 1 nhịp ngắn
  digitalWrite(VIB_PIN, HIGH); delay(90);
  digitalWrite(VIB_PIN, LOW);
}


bool getJson(const String &url, DynamicJsonDocument &doc) {
  if (WiFi.status() != WL_CONNECTED) return false;

  HTTPClient http;
  http.setTimeout(2200);
  http.begin(url);

  int code = http.GET();
  if (code != 200) {
    http.end();
    return false;
  }

  String body = http.getString();
  http.end();
  return deserializeJson(doc, body) == DeserializationError::Ok;
}

bool postAction(
  int notificationId,
  const String &action,
  String &replyMessage,
  int &returnedLevel
) {
  returnedLevel = -1;

  if (WiFi.status() != WL_CONNECTED) {
    replyMessage = "Mat WiFi";
    return false;
  }

  HTTPClient http;
  http.setTimeout(2500);
  http.begin(String(SERVER) + "/api/band/action");
  http.addHeader("Content-Type", "application/json");

  DynamicJsonDocument req(320);
  req["device_id"] = DEVICE_ID;
  req["notification_id"] = notificationId;
  req["action"] = action;

  String body;
  serializeJson(req, body);

  int code = http.POST(body);
  if (code != 200) {
    replyMessage = "Server loi";
    http.end();
    return false;
  }

  DynamicJsonDocument res(768);
  DeserializationError err = deserializeJson(res, http.getString());
  if (err) {
    replyMessage = "JSON loi";
    http.end();
    return false;
  }

  replyMessage = String((const char*)(res["message"] | "Da ghi nhan"));
  returnedLevel = res["level"] | -1;
  bool ok = res["success"] | false;

  http.end();
  return ok;
}


void pollState() {
  DynamicJsonDocument doc(1280);

  if (!getJson(String(SERVER) + "/api/band/state", doc)) return;

  hasTask = doc["has_task"] | false;
  promptLevel = doc["prompt_level"] | -1;

  if (hasTask) {
    taskTitle = String((const char*)(doc["task"]["title"] | ""));
    taskStep  = String((const char*)(doc["task"]["step"] | ""));

    String dt = String((const char*)(doc["task"]["scheduled_at"] | ""));
    taskTime = dt.length() >= 16 ? dt.substring(11, 16) : dt;
  } else {
    taskTitle = "";
    taskStep = "";
    taskTime = "";
  }

  if (screen == HOME) drawHome();
}

void parseMessage(const String &message) {
  int sep = message.indexOf('|');
  if (sep >= 0) {
    notificationTitle = message.substring(0, sep);
    notificationHint = message.substring(sep + 1);
  } else {
    notificationTitle = message;
    notificationHint = "";
  }
}

void pollNotification() {
  DynamicJsonDocument doc(1280);

  if (!getJson(String(SERVER) + "/api/band/next", doc)) return;
  if (!(doc["has_message"] | false)) return;

  int id = doc["id"] | -1;
  if (id < 0) return;

  String typ = String((const char*)(doc["type"] | ""));
  String msg = String((const char*)(doc["message"] | ""));

  currentNotificationId = id;
  notificationType = typ;
  parseMessage(msg);

  // Chỉ rung một lần cho mỗi notification id.
  if (id != lastBuzzedNotificationId) {
    lastBuzzedNotificationId = id;

    if (typ == "MEMORY2") vibrateLevel2();
    else if (typ == "MEMORY1") vibrateLevel1();
    else if (typ == "MEMORY0") vibrateLevel0Check();
    else vibrateLevel2();
  }

  // MEMORY notifications được ưu tiên mở.
  if (typ == "MEMORY2") {
    if (screen != MEMORY2_VIEW) drawMemory2();
  } else if (typ == "MEMORY1") {
    if (screen != MEMORY1_VIEW) drawMemory1();
  } else if (typ == "MEMORY0") {
    if (screen != MEMORY0_VIEW) drawMemory0();
  } else {

    if (screen != MEMORY2_VIEW) {
      notificationTitle = notificationTitle.length() ? notificationTitle : "Nhiem vu";
      drawMemory2();
    }
  }
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  clearScreen();
  centerText("OneStep", 72, 3, C_INK);
  centerText("Dang ket noi WiFi...", 122, 1, C_MUTED);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 12000) {
    delay(250);
  }
}


void sendMemoryAction(const String &action, const String &okText) {
  String msg;
  int newLevel = -1;

  bool ok = postAction(
    currentNotificationId,
    action,
    msg,
    newLevel
  );

  if (newLevel >= 0) promptLevel = newLevel;

  if (ok) {
    currentNotificationId = -1;
    pollState();
    drawResult(okText, newLevel >= 0 ? "Memory level: " + String(newLevel) : "");
  } else {
    drawResult("Khong gui duoc", shortText(msg, 24));
  }
}


void handleTouch(int x, int y) {
  if (millis() - lastTouch < 250) return;
  lastTouch = millis();
  tapHaptic();

  if (screen == HOME) {
    if (inside(x, y, 30, 124, 112, 166)) { drawTaskView(); return; }
    if (inside(x, y, 128, 124, 210, 166)) { drawFocusView(); return; }
    if (inside(x, y, 30, 176, 112, 218)) { drawWaterView(); return; }
    if (inside(x, y, 128, 176, 210, 218)) { drawStatusView(); return; }
  }

  // Back lớn: chỉ áp dụng các màn hình thường, không đóng memory prompt bằng BACK.
  if (
    screen != HOME &&
    screen != MEMORY2_VIEW &&
    screen != MEMORY1_VIEW &&
    screen != MEMORY0_VIEW &&
    inside(x, y, 5, 5, 78, 74)
  ) {
    drawHome();
    return;
  }

  if (screen == TASK_VIEW) {
    if (inside(x, y, 44, 170, 196, 232)) drawHome();
    return;
  }

  if (screen == FOCUS_VIEW) {
    if (inside(x, y, 54, 148, 186, 214)) {
      focusRunning = !focusRunning;
      focusLastTick = millis();
      drawFocusView();
    }
    return;
  }

  if (screen == WATER_VIEW) {
    if (inside(x, y, 54, 168, 186, 226)) {
      waterCount++;
      vibrateLevel1();
      drawWaterView();
    }
    return;
  }

  if (screen == STATUS_VIEW) {
    if (inside(x, y, 54, 176, 186, 232)) {
      pollState();
      drawStatusView();
    }
    return;
  }


  if (screen == MEMORY2_VIEW) {
    if (inside(x, y, 5, 162, 82, 228)) {
      sendMemoryAction("REMEMBER", "Da ghi nhan NHO");
      return;
    }
    if (inside(x, y, 82, 162, 158, 228)) {
      sendMemoryAction("DONE", "Tot! Da hoan thanh");
      return;
    }
    if (inside(x, y, 158, 162, 235, 228)) {
      sendMemoryAction("FORGOT", "Da ghi nhan KHONG NHO");
      return;
    }
  }


  if (screen == MEMORY1_VIEW) {
    if (inside(x, y, 18, 162, 120, 230)) {
      // Backend giữ Level 1; Band không tự xác minh được tên task.
      sendMemoryAction("REMEMBER", "Da ghi nhan NHO");
      return;
    }
    if (inside(x, y, 120, 162, 222, 230)) {
      // Một lần quên không lập tức tăng lên Level 2.
      sendMemoryAction("FORGOT", "Da ghi nhan KHONG NHO");
      return;
    }
  }


  if (screen == MEMORY0_VIEW) {
    if (inside(x, y, 5, 160, 82, 230)) {
      sendMemoryAction("DONE", "Tot! Tu nho va lam");
      return;
    }
    if (inside(x, y, 82, 160, 158, 230)) {
      // Người dùng nhớ việc nhưng chưa thực hiện.
      sendMemoryAction("REMEMBER_NOT_DONE", "Nho, chua lam");
      return;
    }
    if (inside(x, y, 158, 160, 235, 230)) {
      sendMemoryAction("FORGOT", "Da ghi nhan KHONG NHO");
      return;
    }
  }

  if (screen == RESULT_VIEW) {
    if (inside(x, y, 44, 166, 196, 232)) {
      drawHome();
      return;
    }
  }
}


void updateFocus() {
  if (!focusRunning) return;

  if (millis() - focusLastTick >= 1000) {
    focusLastTick = millis();

    if (focusSeconds > 0) {
      focusSeconds--;
      if (screen == FOCUS_VIEW) drawFocusView();
    } else {
      focusRunning = false;
      focusSeconds = 25 * 60;
      vibrateLevel2();
      if (screen == FOCUS_VIEW) drawResult("Het 25 phut", "Nghi mot chut nhe");
    }
  }
}


void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(LCD_BL, OUTPUT);
  digitalWrite(LCD_BL, HIGH);

  pinMode(VIB_PIN, OUTPUT);
  digitalWrite(VIB_PIN, LOW);

  Wire.begin(TP_SDA, TP_SCL);
  touchReset();

  gfx->begin();
  gfx->fillScreen(C_BG);

  connectWiFi();
  pollState();
  drawHome();
}

void loop() {
  int x, y;

  if (readTouch(x, y)) {
    Serial.printf("Touch: %d,%d\n", x, y);
    handleTouch(x, y);
  }

  updateFocus();

  if (millis() - lastPoll >= POLL_MS) {
    lastPoll = millis();

    pollNotification();

    if (
      screen != MEMORY2_VIEW &&
      screen != MEMORY1_VIEW &&
      screen != MEMORY0_VIEW
    ) {
      pollState();
    }
  }

  delay(12);
}
