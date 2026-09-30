#include "Wire.h"
#include "MechLung.ino"
#include <cassert>
#include <iostream>
int main() {
  initPresets(); corrected_centre_dac=applyDacCorrection(DAC_CENTRE);
  startPreset(0); const auto &p=presets[0]; int phase; float target;
  assert(std::abs(p.a_mm*computeKarea()-700)<.001);
  assert(std::abs(commandedFlowSlm(p.t_exp_us/2,phase,target)-5)<.001 && phase==0);
  assert(std::abs(commandedFlowSlm(p.t_exp_us+p.t_insp_us/2,phase,target)+10)<.001 && phase==1);
  assert(sdpCheckCrc(0xbe,0xef,0x92));
  assert(timeReachedUs(20,0xfffffff0)); assert(!timeReachedUs(0xfffffff0,20));
  writeActuatorDac(5000); assert(actuator_clamped); startPreset(0); assert(!actuator_clamped);
  auto command=stepDac(12345); analogRead(A1); assert(last_dac_out==command);
  std::cout << "PASS geometry phase CRC deadline_wrap clamp feedback\n";
}
