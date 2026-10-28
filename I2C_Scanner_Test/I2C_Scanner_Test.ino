#include <Wire.h>

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(115200);
  while (!Serial && millis() < 3000) { }

#if defined(PIN_WIRE_SDA) && defined(PIN_WIRE_SCL)
  pinMode(PIN_WIRE_SDA, INPUT_PULLUP);
  pinMode(PIN_WIRE_SCL, INPUT_PULLUP);
  delay(20);
#endif

  Wire.begin();
  Wire.setClock(100000);

  Serial.println();
  Serial.println("I2C scanner starting");
#if defined(PIN_WIRE_SDA) && defined(PIN_WIRE_SCL)
  Serial.print("SDA idle=");
  Serial.print(digitalRead(PIN_WIRE_SDA));
  Serial.print(" SCL idle=");
  Serial.println(digitalRead(PIN_WIRE_SCL));
#endif
}

void loop() {
  byte count = 0;

#if defined(PIN_WIRE_SDA) && defined(PIN_WIRE_SCL)
  Serial.print("SDA=");
  Serial.print(digitalRead(PIN_WIRE_SDA));
  Serial.print(" SCL=");
  Serial.println(digitalRead(PIN_WIRE_SCL));
#endif

  const byte common[] = {0x18, 0x19, 0x1C, 0x1D, 0x28, 0x29, 0x68, 0x69, 0x6A, 0x6B, 0x76, 0x77};
  Serial.println("Common sensor probes:");
  for (byte i = 0; i < sizeof(common); ++i) {
    byte address = common[i];
    Wire.beginTransmission(address);
    byte error = Wire.endTransmission();
    Serial.print("  0x");
    if (address < 16) Serial.print("0");
    Serial.print(address, HEX);
    Serial.print(" -> ");
    Serial.println(error == 0 ? "ACK" : "no");
  }

  Serial.println("Scanning I2C addresses...");
  for (byte address = 8; address < 120; ++address) {
    Wire.beginTransmission(address);
    byte error = Wire.endTransmission();

    if (error == 0) {
      Serial.print("Found 0x");
      if (address < 16) Serial.print("0");
      Serial.println(address, HEX);
      ++count;
    } else if (error == 4) {
      Serial.print("Unknown error at 0x");
      if (address < 16) Serial.print("0");
      Serial.println(address, HEX);
    }
  }

  Serial.print("Scan complete, devices found: ");
  Serial.println(count);
  Serial.println();

  digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
  delay(2000);
}
