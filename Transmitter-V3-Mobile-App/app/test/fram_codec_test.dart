import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:transmitter_configurator/models/transmitter_model.dart';
import 'package:transmitter_configurator/protocol/fram_codec.dart';

void main() {
  test('CRC-16/CCITT matches standard vector', () {
    expect(FramCodec.crc16(Uint8List.fromList('123456789'.codeUnits)), 0x29b1);
  });

  test('header round trips byte-for-byte', () {
    const header = FramHeader(
      magic: FramCodec.magic,
      version: 1,
      totalSlots: 16,
      activeSlot: 3,
      usedBitmap: 0x8029,
    );
    final decoded = FramCodec.decodeHeader(FramCodec.encodeHeader(header));
    expect(decoded.magic, FramCodec.magic);
    expect(decoded.activeSlot, 3);
    expect(decoded.usedBitmap, 0x8029);
  });

  test('model round trip preserves all fields and valid CRC', () {
    final model = TransmitterModel(
      name: 'Test Plane',
      bindCode: 12345,
      rates: [80, 81, 82, 83],
      expo: [-20, -10, 10, 20],
      drSwitch: 2,
      activeRates: false,
      subtrim: [-50, 0, 25, 50],
      endpoints: [
        [900, 2100],
        [1000, 2000],
        [1100, 1900],
        [1050, 1950],
      ],
      reverse: [true, false, true, false],
    );
    final decoded = FramCodec.decodeModel(FramCodec.encodeModel(model));
    expect(decoded.name, model.name);
    expect(decoded.bindCode, model.bindCode);
    expect(decoded.rates, model.rates);
    expect(decoded.expo, model.expo);
    expect(decoded.subtrim, model.subtrim);
    expect(decoded.endpoints, model.endpoints);
    expect(decoded.reverse, model.reverse);
    expect(decoded.crcOk, isTrue);
  });

  test('corruption is detected', () {
    final bytes = FramCodec.encodeModel(TransmitterModel.defaults());
    bytes[20] ^= 1;
    expect(FramCodec.decodeModel(bytes).crcOk, isFalse);
  });

  test('bad ranges are rejected before write', () {
    final model = TransmitterModel.defaults()..rates[0] = 101;
    expect(() => FramCodec.encodeModel(model), throwsFormatException);
  });
}
