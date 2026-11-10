#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

const uint8_t OLED_ADDR = 0x3D;
const int16_t SCREEN_W = 128;
const int16_t SCREEN_H = 64;

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(115200);
  while (!Serial && millis() < 2000) { }

  Wire.begin();
  Wire.setClock(400000);

  Serial.println("Tx OLED test starting");
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println("SSD1306 init failed at 0x3D");
    while (true) {
      digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
      delay(150);
    }
  }

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("Altitude Unknown");
  display.println("Transmitter Setup");
  display.println();
  display.println("Reverse  Rates");
  display.println("Expo     Trims");
  display.println();
  display.println("OLED 0x3D OK");
  display.display();
  Serial.println("SSD1306 init OK");
}

void loop() {
  static uint32_t lastMs = 0;
  static uint16_t counter = 0;
  uint32_t now = millis();
  if (now - lastMs < 500) return;
  lastMs = now;

  digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));

  display.fillRect(72, 56, 56, 8, SSD1306_BLACK);
  display.setCursor(72, 56);
  display.print("T ");
  display.print(counter++);
  display.display();
}
