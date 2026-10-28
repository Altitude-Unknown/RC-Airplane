// Included after the real firmware by test_autolevel.py; no controller clone.
static void readyController() {
 apState=AutopilotState{}; imu=ImuState{}; apConfig=AutopilotConfig{};
 imuMount=AttitudeControl::Mount{}; controlDtS=.01f;
 armed=true;acceptedPackets=1;lastRxMs=testNow;
 imu.ready=imu.healthy=imu.attitudeInitialized=imu.gyroBiasReady=true;
 imu.lastSampleMs=testNow;imu.lastSampleUs=micros();imu.accelRefG=1;imu.fault="ok";
 apState.neutralCaptured=apState.pilotAutolevelEnabled=true;
 apConfig.autolevelRampMs=0;
 manual_a=manual_e=cur_a=cur_e=1500;manual_t=1000;
}
static void tickController(int count) {
 for(int i=0;i<count;i++){testNow+=10;imu.lastSampleMs=testNow;updateAutopilotState(testNow,0);applyManualOrAutopilotDesired();cur_a=des_a;cur_e=des_e;}
}
static void sampleWord(int offset,int16_t word) {
 sensorBus.sample[offset]=word&255;sensorBus.sample[offset+1]=(word>>8)&255;
}
static bool extraScenario(const std::string &test) {
 if(test=="fbwa_commands") {
  readyController();manual_a=2000;tickController(150);
  assert(apState.mode==AP_MODE_LEVEL_HOLD && apState.commandedRollDeg>29.9f);
  assert(apState.aileronCorrectionUs>0 && apState.aileronCorrectionUs<=160);
  imu.rollDeg=-30;tickController(100);assert(abs(apState.aileronCorrectionUs)<=1);
  manual_a=1500;tickController(100);assert(apState.aileronCorrectionUs<0);
  manual_e=2000;tickController(150);assert(apState.commandedPitchDeg>19.9f);
  manual_e=1000;tickController(200);assert(apState.commandedPitchDeg < -14.9f);
  setPilotAutolevelEnabled(false,"aux-off");tickController(1);
  assert(apState.mode==AP_MODE_MANUAL && des_e==1000 && des_a==1500);
 } else if(test=="noise_and_damping") {
  readyController();tickController(100);
  for(int i=0;i<1000;i++) {
   imu.rollDeg=.1f*sinf(i);imu.pitchDeg=.1f*cosf(i);
   imu.filteredRollDps=.05f*sinf(i);imu.filteredPitchDps=.05f*cosf(i);
   tickController(1);assert(abs(apState.aileronCorrectionUs)<=1 && abs(apState.elevatorCorrectionUs)<=1);
  }
  imu.rollDeg=imu.pitchDeg=0;imu.filteredRollDps=-40;
  tickController(10);assert(apState.aileronCorrectionUs<0); // oppose positive body roll
  imu.filteredRollDps=40;tickController(10);assert(apState.aileronCorrectionUs>0);
 } else if(test=="ground_integral") {
  readyController();imu.rollDeg=-20;tickController(2000);
  assert(apState.rollRateIntegrator==0);
  imu.rollDeg=0;tickController(100);assert(abs(apState.aileronCorrectionUs)<=1);
 } else if(test=="antiwindup") {
  readyController();apState.launchThrottleSeen=true;apState.launchThrottleSeenMs=testNow-6000;
  imu.rollDeg=-40;tickController(3000);
  assert(fabsf(apState.rollRateIntegrator)<.001f && apState.aileronCorrectionUs==-160);
  imu.rollDeg=40;tickController(30);assert(apState.aileronCorrectionUs==160);
  // Final mechanical limits must constrain the automatic command too.
  apConfig.aileronMinUs=1450;apConfig.aileronMaxUs=1550;tickController(100);
  assert(des_a<=1550 && fabsf(apState.rollRateIntegrator)<.001f);
 } else if(test=="invalid_numbers") {
  for(float bad: {INFINITY,-INFINITY,NAN}) {
   readyController();imu.rollDeg=bad;tickController(1);
   assert(!apState.pilotAutolevelEnabled && des_a==1500);
   readyController();apState.rollRateIntegrator=bad;tickController(1);
   assert(!apState.pilotAutolevelEnabled && isfinite(apState.rollRateIntegrator));
  }
  readyController();imu.rollDeg=INFINITY;loop();
  assert(!apState.pilotAutolevelEnabled && armed);
 } else if(test=="sample_health") {
  readyController();sensorBus.sample.assign(12,0);updateImuEstimate(testNow,false);
  assert(!imu.healthy && imu.rejectedSamples==1);
  readyController();sensorBus.status=0;testNow+=40;updateImuEstimate(testNow,false);
  assert(!imu.healthy && imu.samples==0);
  readyController();sensorBus.status=3;sensorBus.sample.assign(12,0);sampleWord(10,-8192);sampleWord(0,29000);
  updateImuEstimate(testNow,false);assert(!imu.healthy);
  readyController();sampleWord(0,0);testNow+=40;updateImuEstimate(testNow,false);
  assert(!imu.healthy && !imu.gyroBiasReady && !apState.neutralCaptured);
 } else if(test=="estimator_rejection") {
  readyController();setQuaternionFromRollPitch(30,0);sensorBus.sample.assign(12,0);sampleWord(10,-8192);
  for(int i=0;i<320;i++){testNow+=10;updateImuEstimate(testNow,false);}
  assert(!imu.healthy && strcmp(imu.fault,"gravity-disagreement")==0);
  assert(imu.rollDeg>29); // no unsafe snap to gravity to regain eligibility
 } else if(test=="calibration_motion") {
  imu=ImuState{};imu.ready=true;beginCalibration();sensorBus.sample.assign(12,0);
  // 1 deg/s motion passes the raw-rate threshold but fails pose stability.
  sampleWord(0,114);
  for(int i=0;i<300;i++) {
   float roll=i*.01f*RAD_PER_DEG;
   sampleWord(8,lroundf(-sinf(roll)/LSM6DS_ACCEL_G_PER_LSB));
   sampleWord(10,lroundf(-cosf(roll)/LSM6DS_ACCEL_G_PER_LSB));
   testNow+=10;updateImuEstimate(testNow,true);
  }
  assert(!imu.gyroBiasReady);
  sampleWord(0,0);sampleWord(8,-4096);sampleWord(10,-7094);
  for(int i=0;i<250;i++){testNow+=10;updateImuEstimate(testNow,true);}
  assert(imu.gyroBiasReady && imu.healthy);
  assert(fabsf(imu.rollDeg)<.2f && fabsf(imu.pitchDeg)<.2f);
 } else if(test=="mount_transform") {
  AttitudeControl::Mount mount;assert(mount.setGravity(.3f,.4f,.8660254f));
  float x=.3f,y=.4f,z=.8660254f;mount.rotate(x,y,z);
  assert(fabsf(x)<.0001f && fabsf(y)<.0001f && fabsf(z-1)<.0001f);
  for(int i=0;i<3;i++)for(int j=0;j<3;j++) {
   float dot=0;for(int k=0;k<3;k++)dot+=mount.m[i][k]*mount.m[j][k];
   assert(fabsf(dot-(i==j ? 1:0))<.0001f);
  }
  assert(!mount.setGravity(0,0,0));
 } else if(test=="failsafe_mixed") {
  readyController();manual_t=1800;des_t=cur_t=1800;des_a=cur_a=1700;
  testNow+=160;loop();assert(cur_a==1700 && cur_t==1800);
  testNow+=1050;loop();assert(!armed && cur_t==1000 && cur_a==1700);
  testNow+=10;loop();assert(cur_a==1500); // preserve existing disarmed manual selection
 } else if(test=="timing_fault") {
  readyController();TimerServos::fault=true;loop();
  assert(!armed && cur_t==1000 && cur_a==1500 && !apState.pilotAutolevelEnabled);
 } else if(test=="rate_dt") {
  // Integral growth depends on elapsed time, not iteration count.
  for(float dt: {.005f,.01f,.02f}) {
   float integral=0,output=0;
   for(int i=0;i<(int)lroundf(2/dt);i++) {
    auto r=AttitudeControl::rate(1,0,.008f,.004f,.00035f,dt,-.32f,.32f,output,1,integral,.12f,true);
    output=r.output;
   }
   assert(integral>.0006f && integral<.00071f);
  }
 } else return false;
 return true;
}
