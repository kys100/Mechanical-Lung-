#include "Wire.h"
#include "MechLung.ino"
#include <cassert>
#include <iostream>
#include <set>
#include <cfloat>
static void initialize() {
  Wire1.pressure = true;
  sfm_ok = true;
  monitor_enabled = false;
  initPresets();
  corrected_centre_dac = applyDacCorrection(DAC_CENTRE);
  slot_us = phase_update_us = micros();
}
static void frame(const std::string &text) {
  for (char c : text) Serial.rx.push_back(c);
  while (Serial.available()) handleSerial();
}
static void tick(uint32_t us = 37) {
  fake_us += us;
  const auto before = transactions.size();
  loop();
  assert(transactions.size() - before <= 1);
}
static void runFor(uint32_t duration) {
  const auto until = fake_us + duration;
  while (fake_us < until) tick();
}
static std::vector<std::string> fields(const std::string &s) {
  std::vector<std::string> result;
  std::istringstream stream(s);
  std::string f;
  while (std::getline(stream, f, ',')) result.push_back(f);
  return result;
}
static std::vector<std::string> dataRows() {
  std::vector<std::string> result;
  std::istringstream stream(Serial.text);
  std::string row;
  while (std::getline(stream,row)) if (row.rfind("DATA",0)==0) result.push_back(row);
  return result;
}
int main(int argc, char **argv) {
  assert(argc == 2);
  initialize();
  const std::string name = argv[1];
  if (name == "geometry") {
    startPreset(0);
    const auto &p = presets[0]; int phase; float target;
    assert(std::abs(p.a_mm*computeKarea()-700)<.001);
    assert(std::abs(commandedFlowSlm(p.t_exp_us/2,phase,target)-5)<.001 && phase==0);
    assert(std::abs(commandedFlowSlm(p.t_exp_us+p.t_insp_us/2,phase,target)+10)<.001 && phase==1);
    assert(sdpCheckCrc(0xbe,0xef,0x92));
    assert(timeReachedUs(20,0xfffffff0)); assert(!timeReachedUs(0xfffffff0,20));
    writeActuatorDac(5000); assert(actuator_clamped);
    startPreset(0); assert(!actuator_clamped);
    auto command = stepDac(12345); readPotAsDacEquivalent(); assert(last_dac_out==command);
  } else if (name == "tx_zero_capacity" || name == "tx_disconnect") {
    frame("@START,0123456789abcdef,P0\n");
    if (name == "tx_zero_capacity") Serial.capacity=0;
    else Serial.connected=false;
    runFor(3010000);
    assert(current_preset==-1 && last_dac_out==corrected_centre_dac);
    assert(!Serial.text.size());
    assert(tx_dropped_total>0 && tx_count<=TX_COUNT);
    Serial.connected=true; Serial.capacity=64;
    runFor(100000);
    assert(Serial.text.find("# ENDED,2,0123456789abcdef")!=std::string::npos);
  } else if (name == "tx_partial_capacity" || name == "tx_record_order") {
    Serial.capacity=3;
    enqueueText("alpha\n"); enqueueText("beta\n",true);
    for(int i=0;i<20;i++) serviceTx();
    assert(Serial.text=="alpha\nbeta\n");
  } else if (name == "tx_overflow") {
    for(int i=0;i<20;i++) enqueueText("telemetry\n",false,true);
    assert(tx_count==6 && tx_dropped_total==14);
    frame("@START,0123456789abcdef,P0\n");
    assert(current_preset==0 && tx_count==7);
    for(int i=0;i<30;i++) frame("@START,0123456789abcdef,P0\n");
    assert(tx_count==7);
    frame("@STOP,0123456789abcdef\n");
    assert(tx_count==8 && current_preset==-1);
    frame("@START,fedcba9876543210,P0\n"); assert(current_preset==-1);
    size_t used=TX_SIZE-2;
    assert(!appendField(used,"%.100f",DBL_MAX)); assert(used==TX_SIZE-2);
  } else if (name == "rx_flood_budget") {
    Serial.rx=std::deque<char>(10000,'m'); handleSerial();
    assert(Serial.rx.size()==9968);
    frame("@START,0123456789abcdef,P0\n");
    Serial.rx=std::deque<char>(100000,'m'); runFor(3010000); assert(current_preset==-1);
  } else if (name == "watchdog_ownership") {
    frame("!H1"); assert(host_watchdog_armed); runFor(3010000); assert(current_preset==-1);
    host_seen=false; frame("1"); runFor(3010000); assert(current_preset==0);
    goIdleHold(); frame("@START,0123456789abcdef,P0\n");
    runFor(500000); const auto previous_seq=seq;
    frame("@START,0123456789abcdef,P0\n"); assert(seq==previous_seq);
    frame("@PING,fedcba9876543210\n"); runFor(2510000); assert(current_preset==-1);
    frame("@START,0123456789abcdef,P0\n"); assert(current_preset==-1);
  } else if (name == "malformed_frames") {
    frame("@START,12345,P0\n"); assert(current_preset==-1);
    frame("@START,"+std::string(100,'1')+"\n"); assert(current_preset==-1);
    frame("@START,012345"); fake_us+=250000; handleSerial();
    frame("6789abcdef,P0\n"); assert(current_preset==-1);
    frame("@START,0123456789abcdef,P0,garbage\n"); assert(current_preset==-1);
  } else if (name == "healthy_schedule" || name == "micros_wrap") {
    if(name=="micros_wrap") fake_us=0xffff0000;
    frame("@START,0123456789abcdef,P0\n"); runFor(500000);
    frame("@STOP,0123456789abcdef\n"); runFor(100000);
    auto rows=dataRows(); assert(rows.size()>=45 && rows.size()<=50);
    std::set<unsigned long> scans;
    for(const auto &r:rows) {
      auto f=fields(r); assert(f.size()==44);
      assert(f[4]=="1"); for(int i=14;i<21;i++) assert(f[i]=="1");
      assert(f[42]=="0"); assert(scans.insert(std::stoul(f[38])).second);
    }
    for(const auto &t:transactions) if(t.bus==1 && t.read) assert(t.channel>=0 && t.channel<7);
    assert(Serial.text.rfind("# ENDED")>Serial.text.rfind("DATA2"));
  } else if(name=="fault_budget") {
    Wire.fail=Wire1.fail=true; Serial.capacity=0;
    frame("@START,0123456789abcdef,P0\n"); runFor(3010000);
    assert(current_preset==-1);
    for(size_t i=1;i<dac_times.size();i++) assert(uint32_t(dac_times[i]-dac_times[i-1])<=16000);
    assert(dac_times.back()-1000000<=3010000);
    std::set<int> selections;
    for(const auto &t:transactions) if(t.bus==1) selections.insert(t.channel);
    assert(selections.size()==7);
    for(int channel=0;channel<7;channel++) assert(selections.count(channel));
  } else if(name=="sfm_crc") {
    assert(sfmCheckCrc(0,0,0));
    assert(sfmCheckCrc(0xbe,0xef,0x13));
    assert(!sfmCheckCrc(0xbe,0xef,0x92));
    uint16_t value;
    assert(sfm3000ReadRaw(value) && value==33400 && Wire.requested==3);
    Wire.corrupt=true;
    assert(!sfm3000ReadRaw(value));
    assert(!sfm3000Init());
    sfm_ok=false;
    sfm_recovery_state=SFM_RECOVERY_DISCARD_WAIT;
    sfm_recovery_due_us=micros();
    sfm3000Service(micros());
    assert(!sfm_ok);
    Wire.corrupt=false; Wire.short_read=true;
    assert(!sfm3000ReadRaw(value));
    assert(sdpCheckCrc(0xbe,0xef,0x92));
  } else if(name=="drop_counter_reset") {
    Serial.capacity=0;
    frame("@START,0123456789abcdef,P0\n");runFor(200000);
    assert(tx_dropped_total>0);
    frame("@STOP,0123456789abcdef\n");
    Serial.capacity=64;runFor(100000);
    Serial.text.clear();
    frame("@START,fedcba9876543210,P0\n");runFor(200000);
    frame("@STOP,fedcba9876543210\n");runFor(100000);
    assert(tx_dropped_total==0);
    assert(Serial.text.find("host_stop,0\n")!=std::string::npos);
  } else if(name=="recovery_wait") {
    psens[0].recovery_state=SDP_RECOVERY_RETRY_WAIT;
    scan_active=true;scan_ch=0;sensor_step=1;
    serviceSensors();assert(sensor_step==2);
    const auto before=micros();serviceSensors();
    assert(psens[0].recovery_due_us==before+50+1000);
    assert(transactions.back().channel==0);
    assert(psens[0].recovery_state==SDP_RECOVERY_WAIT_START);
    fake_us=psens[0].recovery_due_us;
    scan_ch=0;sensor_step=1;serviceSensors();serviceSensors();
    assert(psens[0].recovery_state==SDP_RECOVERY_WAIT_READY);
    assert(psens[0].recovery_due_us==micros()+25000);
    assert(transactions.back().channel==0);
  } else if(name=="metadata") {
    frame("?"); runFor(100000);
    assert(Serial.text.find("# META_BEGIN,2,")!=std::string::npos);
    assert(Serial.text.find("# META,2,dac_centre,1450")!=std::string::npos);
    assert(Serial.text.find("# META_END")<Serial.text.find("# READY_QUERY"));
  } else {
    assert(false);
  }
  std::cout << "PASS " << name << '\n';
}
