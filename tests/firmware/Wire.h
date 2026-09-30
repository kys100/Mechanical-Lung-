#pragma once
#include <cstdint>
#include <cmath>
#include <algorithm>
#include <string>
#include <vector>
#include <sstream>
#include <iomanip>
#include <deque>
#define PI 3.14159265358979323846
#define A0 0
#define A1 1
#define SDA 18
#define SCL 19
#define INPUT_PULLUP 0
#define OUTPUT 1
#define INPUT 2
#define LOW 0
#define HIGH 1
#define HEX 16
#define F(x) x
using std::size_t;
uint64_t fake_us=1000000;
struct Transaction { uint32_t start; int bus, address, channel; bool read; };
std::vector<Transaction> transactions;
int selected_channel = -1;
uint32_t micros(){return uint32_t(fake_us);}
uint32_t millis(){return uint32_t(fake_us/1000);}
void delay(int ms){fake_us+=ms*1000;}
void delayMicroseconds(int us){fake_us+=us;}
void pinMode(int,int){}
void digitalWrite(int,int){}
int digitalRead(int){return HIGH;}
void analogWriteResolution(int){}
void analogReadResolution(int){}
std::vector<uint32_t> dac_times;
void analogWrite(int,int){dac_times.push_back(micros());}
int analogRead(int){return 1414;}
template<class T> T constrain(T x,T lo,T hi){return std::max(lo,std::min(x,hi));}
struct FakeSerial {
 std::string text; std::deque<char> rx; int capacity=64; bool connected=true;
 int availableForWrite(){return capacity;}
 size_t write(const uint8_t *s,size_t n){if(n>(size_t)capacity) throw 1; if(!connected)return 0; text.append((const char*)s,n); return n;}
 void begin(int){} operator bool(){return true;}
 int available(){return rx.size();} int read(){auto x=rx.front(); rx.pop_front(); return x;}
 template<class T> void print(T x){std::ostringstream s; s<<x; text+=s.str();}
 void print(uint8_t x){print(int(x));}
 template<class T> void print(T x,int precision){std::ostringstream s; s<<std::fixed<<std::setprecision(precision)<<x; text+=s.str();}
 template<class T> void println(T x){print(x);text+='\n';}
 template<class T> void println(T x,int n){print(x,n);text+='\n';}
 void println(){text+='\n';}
} Serial;
uint8_t crc(uint16_t w){uint8_t v=0xff;for(auto b:{uint8_t(w>>8),uint8_t(w)}){v^=b;for(int j=0;j<8;j++)v=v&128?(v<<1)^0x31:v<<1;}return v;}
struct FakeWire {
 bool pressure=false, fail=false, corrupt=false; int scans=0, requested=0, address=0, payload=0; std::deque<uint8_t> rx;
 void begin(){} void setClock(int){} void setWireTimeout(uint32_t,bool){}
 void beginTransmission(int a){address=a;} void write(int v){payload=v;}
 int endTransmission(){
   transactions.push_back({micros(),pressure?1:0,address,selected_channel,false});
   fake_us+=fail?5000:50;
   if(pressure && address==0x70 && !fail){selected_channel=-1;for(int c=0;c<7;c++)if(payload==(1<<c))selected_channel=c;}
   return fail?4:0;
 }
 int requestFrom(int a,int n){transactions.push_back({micros(),pressure?1:0,a,selected_channel,true});requested=n;scans++;fake_us+=fail?5000:200;if(fail)return 0;rx.clear();
   if(!pressure){rx={0x82,0x78,0}; uint8_t v=0; for(uint8_t b:{uint8_t(0x82),uint8_t(0x78)}){v^=b;for(int j=0;j<8;j++)v=v&128?(v<<1)^0x31:v<<1;}rx[2]=corrupt?v^1:v;return n;} // 33400 => 10 slm
   for(uint16_t w:{uint16_t(1200),uint16_t(5000),uint16_t(60)}){rx.push_back(w>>8);rx.push_back(w);rx.push_back(crc(w));}return n;}
 int available(){return rx.size();} int read(){int x=rx.front();rx.pop_front();return x;}
} Wire,Wire1;
