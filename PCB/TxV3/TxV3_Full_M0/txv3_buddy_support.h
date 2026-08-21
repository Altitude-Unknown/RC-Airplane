#pragma once
#include <Arduino.h>

static constexpr uint8_t TXV3_TRAINER_PIN=10;
// The buddy path is flight-critical. At 115200 baud, a LOCAL update occupies
// roughly 3 ms on the wire instead of 15-20 ms at the original bench rate.
static constexpr uint32_t TXV3_UART_BAUD=115200;
static constexpr uint32_t TXV3_LOCAL_INTERVAL_MS=10;
static constexpr uint32_t TXV3_STUDENT_TIMEOUT_MS=250;
static constexpr uint16_t TXV3_MASTER_MOVE_US=35;
static constexpr uint16_t TXV3_PACKET_MAGIC=0xB358;

enum TxV3Role:uint8_t { TXV3_UNKNOWN=0, TXV3_MASTER=1, TXV3_STUDENT=2 };
struct __attribute__((packed)) TxV3StudentPacket {
  uint16_t magic; uint8_t version; uint8_t type; uint16_t sequence;
  uint16_t rudder,aileron,elevator,throttle; uint8_t auxFlags,reserved; uint16_t crc;
};
struct TxV3Channels { uint16_t rud,ail,ele,thr; uint8_t aux; };

static TxV3Role txv3Role=TXV3_UNKNOWN;
static TxV3Channels txv3Student{1500,1500,1500,1000,0};
static TxV3Channels txv3Master{1500,1500,1500,1000,0};
static TxV3Channels txv3MasterAtGrant{1500,1500,1500,1000,0};
static bool txv3StudentFresh=false,txv3StudentGranted=false,txv3AuxWasPressed=false;
static bool txv3LastReportedGrant=true;
static uint32_t txv3StudentReceivedMs=0,txv3LastLocalMs=0;
static uint32_t txv3LastAuthorityHeartbeatMs=0;
static uint32_t txv3LastModeHeartbeatMs=0;
static const char *txv3Mode="UNKNOWN";
static uint16_t txv3LocalSequence=0;
static char txv3Line[48]; static uint8_t txv3LineLength=0;
static uint8_t txv3PacketBytes[sizeof(TxV3StudentPacket)],txv3PacketLength=0;
static constexpr uint16_t TXV3_RX_SIZE=256;
static volatile uint8_t txv3Rx[TXV3_RX_SIZE];
static volatile uint16_t txv3RxHead=0,txv3RxTail=0;

void SERCOM5_Handler(){
  if(SERCOM5->USART.INTFLAG.bit.RXC){
    uint8_t b=SERCOM5->USART.DATA.reg;
    uint16_t n=(txv3RxHead+1)%TXV3_RX_SIZE;
    if(n!=txv3RxTail){txv3Rx[txv3RxHead]=b;txv3RxHead=n;}
  }
  if(SERCOM5->USART.INTFLAG.bit.ERROR){
    SERCOM5->USART.STATUS.reg=SERCOM5->USART.STATUS.reg;
    SERCOM5->USART.INTFLAG.reg=SERCOM_USART_INTFLAG_ERROR;
  }
}

static uint16_t txv3Crc(const uint8_t *p,size_t n){
  uint16_t c=0xffff; while(n--){c^=(uint16_t)*p++<<8;for(uint8_t i=0;i<8;i++)c=(c&0x8000)?(uint16_t)((c<<1)^0x1021):(uint16_t)(c<<1);} return c;
}
static void txv3WaitSync(){while(SERCOM5->USART.SYNCBUSY.reg){}}
static void txv3UartBegin(){
  PM->APBCMASK.reg|=PM_APBCMASK_SERCOM5;
  GCLK->CLKCTRL.reg=GCLK_CLKCTRL_ID(SERCOM5_GCLK_ID_CORE)|GCLK_CLKCTRL_GEN_GCLK0|GCLK_CLKCTRL_CLKEN;
  while(GCLK->STATUS.bit.SYNCBUSY){}
  PORT->Group[1].PMUX[11].bit.PMUXE=PORT_PMUX_PMUXE_D_Val; PORT->Group[1].PMUX[11].bit.PMUXO=PORT_PMUX_PMUXO_D_Val;
  PORT->Group[1].PINCFG[22].bit.PMUXEN=1; PORT->Group[1].PINCFG[23].bit.PMUXEN=1;
  SERCOM5->USART.CTRLA.bit.SWRST=1; while(SERCOM5->USART.CTRLA.bit.SWRST||SERCOM5->USART.SYNCBUSY.bit.SWRST){}
  uint32_t b8=(SystemCoreClock*8UL)/(16UL*TXV3_UART_BAUD);
  SERCOM5->USART.CTRLA.reg=SERCOM_USART_CTRLA_MODE_USART_INT_CLK|SERCOM_USART_CTRLA_SAMPR(1)|SERCOM_USART_CTRLA_TXPO(1)|SERCOM_USART_CTRLA_RXPO(3)|SERCOM_USART_CTRLA_DORD;
  SERCOM5->USART.BAUD.FRAC.FP=b8%8; SERCOM5->USART.BAUD.FRAC.BAUD=b8/8;
  SERCOM5->USART.CTRLB.reg=SERCOM_USART_CTRLB_CHSIZE(0)|SERCOM_USART_CTRLB_TXEN|SERCOM_USART_CTRLB_RXEN;
  txv3WaitSync(); SERCOM5->USART.CTRLA.bit.ENABLE=1; txv3WaitSync();
  SERCOM5->USART.INTENSET.reg=SERCOM_USART_INTENSET_RXC|SERCOM_USART_INTENSET_ERROR;
  NVIC_ClearPendingIRQ(SERCOM5_IRQn); NVIC_SetPriority(SERCOM5_IRQn,3); NVIC_EnableIRQ(SERCOM5_IRQn);
}
static void txv3Write(const char *s){while(*s){while(!SERCOM5->USART.INTFLAG.bit.DRE){}SERCOM5->USART.DATA.reg=*s++;}}
static int txv3Read(){noInterrupts();if(txv3RxTail==txv3RxHead){interrupts();return -1;}uint8_t b=txv3Rx[txv3RxTail];txv3RxTail=(txv3RxTail+1)%TXV3_RX_SIZE;interrupts();return b;}
static void txv3RoleLine(){
  txv3Line[txv3LineLength]=0;
  if(!strcmp(txv3Line,"ROLE MASTER"))txv3Role=TXV3_MASTER;
  else if(!strcmp(txv3Line,"ROLE STUDENT"))txv3Role=TXV3_STUDENT;
  txv3LineLength=0;
}
static void txv3BinaryByte(uint8_t b){
  if(txv3PacketLength==0){if(b!=(TXV3_PACKET_MAGIC&0xff))return;txv3PacketBytes[txv3PacketLength++]=b;return;}
  if(txv3PacketLength==1&&b!=(TXV3_PACKET_MAGIC>>8)){txv3PacketLength=(b==(TXV3_PACKET_MAGIC&0xff));return;}
  txv3PacketBytes[txv3PacketLength++]=b; if(txv3PacketLength<sizeof(TxV3StudentPacket))return;
  TxV3StudentPacket p;memcpy(&p,txv3PacketBytes,sizeof(p));txv3PacketLength=0;uint16_t expected=p.crc;p.crc=0;
  bool bounds=p.rudder>=800&&p.rudder<=2200&&p.aileron>=800&&p.aileron<=2200&&p.elevator>=800&&p.elevator<=2200&&p.throttle>=800&&p.throttle<=2200;
  if(p.magic!=TXV3_PACKET_MAGIC||p.version!=1||p.type!=1||!bounds||txv3Crc((uint8_t*)&p,sizeof(p))!=expected)return;
  txv3Student={p.rudder,p.aileron,p.elevator,p.throttle,p.auxFlags};txv3StudentReceivedMs=millis();txv3StudentFresh=true;
}
static void txv3ReadUart(){
  int v;while((v=txv3Read())>=0){if(txv3Role!=TXV3_UNKNOWN){txv3BinaryByte(v);continue;}char c=(char)v;if(c=='\r')continue;if(c=='\n'){if(txv3LineLength)txv3RoleLine();}else if(txv3LineLength<sizeof(txv3Line)-1)txv3Line[txv3LineLength++]=c;else txv3LineLength=0;}
}
void txv3BuddyBegin(){
  pinMode(TXV3_TRAINER_PIN,INPUT_PULLUP);txv3UartBegin();uint32_t query=0;
  while(txv3Role==TXV3_UNKNOWN){uint32_t now=millis();if(now-query>=100){query=now;txv3Write("ROLE?\n");}txv3ReadUart();delay(1);}txv3Write("READY\n");
}
void txv3BuddyModeOnlyBegin(const char *mode){
  pinMode(TXV3_TRAINER_PIN,INPUT_PULLUP);txv3UartBegin();txv3Mode=mode;char out[32];snprintf(out,sizeof(out),"MODE %s\n",txv3Mode);txv3Write(out);txv3LastModeHeartbeatMs=millis();
}
void txv3BuddySetMode(const char *mode){
  txv3Mode=mode;txv3LastModeHeartbeatMs=0;
}
void txv3BuddyModeService(){
  uint32_t now=millis();if(now-txv3LastModeHeartbeatMs<500)return;txv3LastModeHeartbeatMs=now;char out[32];snprintf(out,sizeof(out),"MODE %s\n",txv3Mode);txv3Write(out);
}
void txv3BuddyService(){
  txv3ReadUart(); if(txv3Role!=TXV3_MASTER)return;uint32_t now=millis();
  bool pressed=digitalRead(TXV3_TRAINER_PIN)==LOW;if(pressed)txv3AuxWasPressed=true;
  if(!pressed&&txv3AuxWasPressed){txv3AuxWasPressed=false;if(txv3StudentGranted)txv3StudentGranted=false;else if(txv3StudentFresh&&now-txv3StudentReceivedMs<=TXV3_STUDENT_TIMEOUT_MS){txv3StudentGranted=true;txv3MasterAtGrant=txv3Master;}}
  auto moved=[](uint16_t a,uint16_t b){return abs((int)a-(int)b)>=TXV3_MASTER_MOVE_US;};
  if(txv3StudentGranted&&(moved(txv3Master.rud,txv3MasterAtGrant.rud)||moved(txv3Master.ail,txv3MasterAtGrant.ail)||moved(txv3Master.ele,txv3MasterAtGrant.ele)||moved(txv3Master.thr,txv3MasterAtGrant.thr)))txv3StudentGranted=false;
  if(now-txv3StudentReceivedMs>TXV3_STUDENT_TIMEOUT_MS){txv3StudentFresh=false;txv3StudentGranted=false;}
  if(txv3StudentGranted!=txv3LastReportedGrant||now-txv3LastAuthorityHeartbeatMs>=1000){txv3LastReportedGrant=txv3StudentGranted;txv3LastAuthorityHeartbeatMs=now;txv3Write(txv3StudentGranted?"AUTHORITY STUDENT\n":"AUTHORITY INSTRUCTOR\n");}
}
bool txv3BuddyIsStudent(){return txv3Role==TXV3_STUDENT;}
void txv3BuddyPublishLocal(uint16_t rud,uint16_t ail,uint16_t ele,uint16_t thr,uint8_t aux){
  uint32_t now=millis();if(now-txv3LastLocalMs<TXV3_LOCAL_INTERVAL_MS)return;txv3LastLocalMs=now;char out[96];snprintf(out,sizeof(out),"LOCAL %u %u %u %u %u %u\n",++txv3LocalSequence,rud,ail,ele,thr,aux);txv3Write(out);
}
bool txv3BuddySelectChannels(uint16_t &rud,uint16_t &ail,uint16_t &ele,uint16_t &thr,uint8_t &aux){
  txv3Master={rud,ail,ele,thr,aux};txv3BuddyService();if(!txv3StudentGranted)return false;rud=txv3Student.rud;ail=txv3Student.ail;ele=txv3Student.ele;thr=txv3Student.thr;aux=txv3Student.aux;return true;
}
