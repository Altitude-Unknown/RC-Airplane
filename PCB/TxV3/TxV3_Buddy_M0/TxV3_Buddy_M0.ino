/*
  Transmitter V3 flight firmware with wireless buddy-box support.

  V2-compatible LoRa ControlPacket. Only an ESP-configured MASTER initializes
  LoRa. A STUDENT sends processed controls to its ESP32 and never transmits LoRa.
  AUX press-release toggles student authority. Any master stick movement or
  stale student data revokes authority and requires another AUX cycle.
*/

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <RH_RF95.h>

// Measured on both assembled prototypes: the gimbal harness follows the V2
// throttle/rudder order even though the corrected V3 schematic labels A0/A3
// oppositely. Physical throttle is A3 (low ~=1020), rudder is A0.
static constexpr uint8_t PIN_THR=A3, PIN_AIL=A1, PIN_ELE=A2, PIN_RUD=A0;
static constexpr uint8_t PIN_TRIM_RUD_L=A4, PIN_TRIM_RUD_R=12;
static constexpr uint8_t PIN_TRIM_AIL_L=1, PIN_TRIM_AIL_R=5;
static constexpr uint8_t PIN_TRIM_ELE_UP=2, PIN_TRIM_ELE_DOWN=0;
static constexpr uint8_t PIN_BIND=9, PIN_AUX=10, PIN_BUZZER=11, STATUS_LED_PIN=13;
static constexpr uint8_t RFM95_CS=8, RFM95_INT=3, RFM95_RST=4;
static constexpr float RF95_FREQ=915.0f;
static constexpr uint16_t RC_MIN=1000, RC_MID=1500, RC_MAX=2000;
static constexpr uint16_t MASTER_MOVE_US=35;
static constexpr uint32_t STUDENT_TIMEOUT_MS=250;
static constexpr uint32_t UART_REPORT_MS=50;
static constexpr uint32_t BUDDY_UART_BAUD=19200;
static constexpr uint8_t AUX_AUTOLEVEL_ON=0x01, AUX_AUTOLEVEL_OFF=0x02;

struct __attribute__((packed)) ControlPacket {
  uint16_t ch_rud, ch_ail, ch_ele, ch_thr;
  uint16_t flags;
  uint8_t aux_flags;
  uint16_t seq;
};
struct __attribute__((packed)) BindPacket { uint32_t magic; uint16_t code; uint16_t pad; };
static constexpr uint32_t BIND_MAGIC=0x42494E44UL;
static constexpr uint16_t SAMD_PACKET_MAGIC=0xB358;
static constexpr uint8_t SAMD_PACKET_VERSION=1;
static constexpr uint8_t SAMD_PACKET_TYPE_STUDENT=1;
struct __attribute__((packed)) SamdStudentPacket {
  uint16_t magic;
  uint8_t version;
  uint8_t type;
  uint16_t sequence;
  uint16_t rudder;
  uint16_t aileron;
  uint16_t elevator;
  uint16_t throttle;
  uint8_t auxFlags;
  uint8_t reserved;
  uint16_t crc;
};

enum Role : uint8_t { ROLE_UNKNOWN=0, ROLE_MASTER=1, ROLE_STUDENT=2 };
struct Channels { uint16_t rud, ail, ele, thr; uint8_t aux; };

RH_RF95 radio(RFM95_CS, RFM95_INT);
Role role=ROLE_UNKNOWN;
Channels local{RC_MID,RC_MID,RC_MID,RC_MIN,0};
Channels student{RC_MID,RC_MID,RC_MID,RC_MIN,0};
Channels masterAtGrant{RC_MID,RC_MID,RC_MID,RC_MIN,0};
ControlPacket packet{};
uint16_t sequence=0;
uint16_t bindCode=0x1234; // receiver-compatible fallback; replace via V3 configurator
bool auxWasPressed=false;
bool studentGranted=false;
bool studentFresh=false;
uint32_t studentReceivedMs=0;
uint32_t lastUartReportMs=0;
uint32_t lastUsbStatusMs=0;
bool lastReportedGrant=false;
char uartLine[112];
size_t uartLength=0;
static constexpr uint16_t UART_RX_BUFFER_SIZE=256;
volatile uint8_t uartRxBuffer[UART_RX_BUFFER_SIZE];
volatile uint16_t uartRxHead=0;
volatile uint16_t uartRxTail=0;
volatile uint32_t uartRxOverflow=0;
volatile uint32_t uartRxErrors=0;
volatile uint32_t uartRxBytes=0;
uint32_t studentLinesAccepted=0;
uint32_t studentLinesRejected=0;
uint8_t binaryPacketBuffer[sizeof(SamdStudentPacket)]={0};
uint8_t binaryPacketLength=0;

void SERCOM5_Handler(){
  if(SERCOM5->USART.INTFLAG.bit.RXC){
    const uint8_t byte=SERCOM5->USART.DATA.reg&0xff;
    ++uartRxBytes;
    const uint16_t next=(uartRxHead+1)%UART_RX_BUFFER_SIZE;
    if(next!=uartRxTail){uartRxBuffer[uartRxHead]=byte;uartRxHead=next;}
    else ++uartRxOverflow;
  }
  if(SERCOM5->USART.INTFLAG.bit.ERROR){
    ++uartRxErrors;
    SERCOM5->USART.STATUS.reg=SERCOM5->USART.STATUS.reg;
    SERCOM5->USART.INTFLAG.reg=SERCOM_USART_INTFLAG_ERROR;
  }
}

static uint16_t crc16(const uint8_t *data,size_t length){
  uint16_t crc=0xffff;
  while(length--){crc^=static_cast<uint16_t>(*data++)<<8;for(uint8_t i=0;i<8;++i)crc=(crc&0x8000)?static_cast<uint16_t>((crc<<1)^0x1021):static_cast<uint16_t>(crc<<1);}
  return crc;
}

static void waitSync(){ while(SERCOM5->USART.SYNCBUSY.reg){} }
static void buddyUartBegin(){
  PM->APBCMASK.reg|=PM_APBCMASK_SERCOM5;
  GCLK->CLKCTRL.reg=GCLK_CLKCTRL_ID(SERCOM5_GCLK_ID_CORE)|GCLK_CLKCTRL_GEN_GCLK0|GCLK_CLKCTRL_CLKEN;
  while(GCLK->STATUS.bit.SYNCBUSY){}
  PORT->Group[1].PMUX[11].bit.PMUXE=PORT_PMUX_PMUXE_D_Val;
  PORT->Group[1].PMUX[11].bit.PMUXO=PORT_PMUX_PMUXO_D_Val;
  PORT->Group[1].PINCFG[22].bit.PMUXEN=1; PORT->Group[1].PINCFG[23].bit.PMUXEN=1;
  SERCOM5->USART.CTRLA.bit.SWRST=1;
  while(SERCOM5->USART.CTRLA.bit.SWRST||SERCOM5->USART.SYNCBUSY.bit.SWRST){}
  const uint32_t b8=(SystemCoreClock*8UL)/(16UL*BUDDY_UART_BAUD);
  SERCOM5->USART.CTRLA.reg=SERCOM_USART_CTRLA_MODE_USART_INT_CLK|SERCOM_USART_CTRLA_SAMPR(1)|SERCOM_USART_CTRLA_TXPO(1)|SERCOM_USART_CTRLA_RXPO(3)|SERCOM_USART_CTRLA_DORD;
  SERCOM5->USART.BAUD.FRAC.FP=b8%8; SERCOM5->USART.BAUD.FRAC.BAUD=b8/8;
  SERCOM5->USART.CTRLB.reg=SERCOM_USART_CTRLB_CHSIZE(0)|SERCOM_USART_CTRLB_TXEN|SERCOM_USART_CTRLB_RXEN;
  waitSync(); SERCOM5->USART.CTRLA.bit.ENABLE=1; waitSync();
  SERCOM5->USART.INTENSET.reg=SERCOM_USART_INTENSET_RXC|SERCOM_USART_INTENSET_ERROR;
  NVIC_ClearPendingIRQ(SERCOM5_IRQn);
  NVIC_SetPriority(SERCOM5_IRQn,3);
  NVIC_EnableIRQ(SERCOM5_IRQn);
}
static void buddyWrite(const char *s){ while(*s){ while(!SERCOM5->USART.INTFLAG.bit.DRE){} SERCOM5->USART.DATA.reg=*s++; } }
static int buddyRead(){
  noInterrupts();
  if(uartRxTail==uartRxHead){interrupts();return -1;}
  const uint8_t byte=uartRxBuffer[uartRxTail];
  uartRxTail=(uartRxTail+1)%UART_RX_BUFFER_SIZE;
  interrupts();
  return byte;
}

static uint16_t mapAxis(uint8_t pin, bool invert=false){
  int raw=analogRead(pin); if(invert) raw=1023-raw;
  return constrain(map(raw,0,1023,RC_MIN,RC_MAX),RC_MIN,RC_MAX);
}
static void readLocal(){
  local.thr=mapAxis(PIN_THR,true); local.ail=mapAxis(PIN_AIL); local.ele=mapAxis(PIN_ELE); local.rud=mapAxis(PIN_RUD);
  local.aux=0;
  if(digitalRead(PIN_TRIM_RUD_L)==LOW)local.aux|=AUX_AUTOLEVEL_ON;
  if(digitalRead(PIN_TRIM_RUD_R)==LOW)local.aux|=AUX_AUTOLEVEL_OFF;
}
static bool moved(uint16_t a,uint16_t b){ return abs(static_cast<int>(a)-static_cast<int>(b))>=MASTER_MOVE_US; }
static bool masterMoved(){ return moved(local.rud,masterAtGrant.rud)||moved(local.ail,masterAtGrant.ail)||moved(local.ele,masterAtGrant.ele)||moved(local.thr,masterAtGrant.thr); }

static void processUart(const char *line){
  if(role==ROLE_UNKNOWN){Serial.print(F("ROLE_UART_RX ["));Serial.print(line);Serial.println(']');}
  if(!strcmp(line,"ROLE MASTER"))role=ROLE_MASTER;
  else if(!strcmp(line,"ROLE STUDENT"))role=ROLE_STUDENT;
  else if(!strcmp(line,"ROLE UNCONFIGURED"))role=ROLE_UNKNOWN;
}

static void processBinaryByte(uint8_t byte){
  if(binaryPacketLength==0){if(byte!=static_cast<uint8_t>(SAMD_PACKET_MAGIC&0xff))return;binaryPacketBuffer[binaryPacketLength++]=byte;return;}
  if(binaryPacketLength==1){
    if(byte!=static_cast<uint8_t>(SAMD_PACKET_MAGIC>>8)){binaryPacketLength=(byte==static_cast<uint8_t>(SAMD_PACKET_MAGIC&0xff))?1:0;return;}
    binaryPacketBuffer[binaryPacketLength++]=byte;return;
  }
  binaryPacketBuffer[binaryPacketLength++]=byte;
  if(binaryPacketLength<sizeof(SamdStudentPacket))return;
  SamdStudentPacket packet;memcpy(&packet,binaryPacketBuffer,sizeof(packet));binaryPacketLength=0;
  const uint16_t expected=packet.crc;packet.crc=0;
  const bool bounds=packet.rudder>=800&&packet.rudder<=2200&&packet.aileron>=800&&packet.aileron<=2200&&packet.elevator>=800&&packet.elevator<=2200&&packet.throttle>=800&&packet.throttle<=2200;
  if(packet.magic!=SAMD_PACKET_MAGIC||packet.version!=SAMD_PACKET_VERSION||packet.type!=SAMD_PACKET_TYPE_STUDENT||!bounds||crc16(reinterpret_cast<const uint8_t*>(&packet),sizeof(packet))!=expected){++studentLinesRejected;return;}
  student={packet.rudder,packet.aileron,packet.elevator,packet.throttle,packet.auxFlags};
  studentReceivedMs=millis();studentFresh=true;++studentLinesAccepted;
}
static void updateUart(){
  int v; while((v=buddyRead())>=0){
    if(role!=ROLE_UNKNOWN){processBinaryByte(static_cast<uint8_t>(v));continue;}
    char c=static_cast<char>(v); if(c=='\r')continue;
    if(c=='\n'){ if(uartLength){uartLine[uartLength]=0;processUart(uartLine);uartLength=0;} }
    else if(uartLength<sizeof(uartLine)-1)uartLine[uartLength++]=c; else uartLength=0;
  }
  const uint32_t now=millis();
  if(now-lastUartReportMs>=UART_REPORT_MS){ lastUartReportMs=now; char out[96];
    snprintf(out,sizeof(out),"LOCAL %u %u %u %u %u %u\n",sequence,local.rud,local.ail,local.ele,local.thr,local.aux); buddyWrite(out);
  }
}

static bool radioBegin(){
  pinMode(RFM95_RST,OUTPUT); digitalWrite(RFM95_RST,LOW);delay(10);digitalWrite(RFM95_RST,HIGH);delay(10);
  if(!radio.init())return false; radio.setModemConfig(RH_RF95::Bw500Cr45Sf128); radio.setFrequency(RF95_FREQ); radio.setTxPower(17,false); return true;
}

void setup(){
  pinMode(STATUS_LED_PIN,OUTPUT); pinMode(PIN_BUZZER,OUTPUT); digitalWrite(PIN_BUZZER,LOW);
  const uint8_t buttons[]={PIN_TRIM_RUD_L,PIN_TRIM_RUD_R,PIN_TRIM_AIL_L,PIN_TRIM_AIL_R,PIN_TRIM_ELE_UP,PIN_TRIM_ELE_DOWN,PIN_BIND,PIN_AUX};
  for(uint8_t pin:buttons)pinMode(pin,INPUT_PULLUP);
  Serial.begin(115200); buddyUartBegin();
  uint32_t lastRoleQueryMs=0;
  uint32_t lastRoleWaitReportMs=0;
  while(role==ROLE_UNKNOWN){
    const uint32_t now=millis();
    if(now-lastRoleQueryMs>=100){lastRoleQueryMs=now;buddyWrite("ROLE?\n");}
    if(now-lastRoleWaitReportMs>=1000){
      lastRoleWaitReportMs=now;
      Serial.println(F("ROLE_WAIT no_valid_esp_role; LoRa disabled"));
    }
    updateUart();delay(1);
  }
  buddyWrite("READY\n");
  if(role==ROLE_MASTER){
    if(!radioBegin()){while(true){digitalWrite(STATUS_LED_PIN,!digitalRead(STATUS_LED_PIN));delay(100);}}
    const int startupThrottleRaw=analogRead(PIN_THR);
    readLocal();
    Serial.print(F("THROTTLE_START raw=")); Serial.print(startupThrottleRaw);
    Serial.print(F(" mapped_us=")); Serial.println(local.thr);
    if(local.thr>1060){
      Serial.println(F("THROTTLE_LOCK lower_throttle_and_reset"));
      uint8_t blinkCount=0;
      while(true){
        digitalWrite(STATUS_LED_PIN,!digitalRead(STATUS_LED_PIN)); delay(100);
        if(++blinkCount>=10){
          blinkCount=0;
          Serial.print(F("THROTTLE_LOCK raw=")); Serial.print(analogRead(PIN_THR));
          Serial.print(F(" mapped_us=")); Serial.print(mapAxis(PIN_THR,true));
          Serial.print(F(" all_adc=")); Serial.print(analogRead(A0));Serial.print(',');
          Serial.print(analogRead(A1));Serial.print(',');Serial.print(analogRead(A2));Serial.print(',');
          Serial.println(analogRead(A3));
        }
      }
    }
  } else if(role==ROLE_STUDENT){ digitalWrite(STATUS_LED_PIN,HIGH); }
  else { while(true){digitalWrite(STATUS_LED_PIN,!digitalRead(STATUS_LED_PIN));delay(500);} }
  Serial.print(F("TXV3_BUDDY_M0_READY role="));
  Serial.println(role==ROLE_MASTER?F("MASTER"):F("STUDENT"));
}

void loop(){
  readLocal(); updateUart(); ++sequence;
  if(role==ROLE_STUDENT){ digitalWrite(STATUS_LED_PIN,(millis()/500)%2); delay(2); return; }

  const bool auxPressed=digitalRead(PIN_AUX)==LOW;
  if(auxPressed)auxWasPressed=true;
  if(!auxPressed&&auxWasPressed){
    auxWasPressed=false;
    if(studentGranted)studentGranted=false;
    else if(studentFresh&&millis()-studentReceivedMs<=STUDENT_TIMEOUT_MS){studentGranted=true;masterAtGrant=local;}
  }
  if(studentGranted&&masterMoved())studentGranted=false;
  if(millis()-studentReceivedMs>STUDENT_TIMEOUT_MS){studentFresh=false;studentGranted=false;}

  const uint32_t now=millis();
  if(studentGranted!=lastReportedGrant){
    lastReportedGrant=studentGranted;
    Serial.print(F("AUTHORITY "));
    Serial.println(studentGranted?F("STUDENT"):F("INSTRUCTOR"));
  }
  if(now-lastUsbStatusMs>=250){
    lastUsbStatusMs=now;
    Serial.print(F("BUDDY_STATUS authority="));
    Serial.print(studentGranted?F("STUDENT"):F("INSTRUCTOR"));
    Serial.print(F(" link=")); Serial.print(studentFresh?F("OK"):F("STALE"));
    Serial.print(F(" uart_overflow=")); Serial.print(uartRxOverflow);
    Serial.print(F(" uart_errors="));Serial.print(uartRxErrors);
    Serial.print(F(" uart_bytes="));Serial.print(uartRxBytes);
    Serial.print(F(" lines_ok="));Serial.print(studentLinesAccepted);
    Serial.print(F(" lines_bad="));Serial.print(studentLinesRejected);
    Serial.print(F(" age_ms=")); Serial.print(studentFresh?now-studentReceivedMs:9999);
    Serial.print(F(" master=")); Serial.print(local.rud);Serial.print(',');Serial.print(local.ail);Serial.print(',');Serial.print(local.ele);Serial.print(',');Serial.print(local.thr);
    Serial.print(F(" student=")); Serial.print(student.rud);Serial.print(',');Serial.print(student.ail);Serial.print(',');Serial.print(student.ele);Serial.print(',');Serial.println(student.thr);
  }

  const Channels &active=studentGranted?student:local;
  packet.ch_rud=active.rud; packet.ch_ail=active.ail; packet.ch_ele=active.ele; packet.ch_thr=active.thr;
  packet.flags=bindCode&0x7fff; packet.aux_flags=active.aux; packet.seq=sequence;
  radio.send(reinterpret_cast<uint8_t*>(&packet),sizeof(packet)); radio.waitPacketSent();
  digitalWrite(STATUS_LED_PIN,studentGranted?((millis()/120)%2):HIGH);
  delay(2);
}
