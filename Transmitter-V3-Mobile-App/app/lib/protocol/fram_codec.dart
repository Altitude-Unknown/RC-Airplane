import 'dart:convert';
import 'dart:typed_data';

import '../models/transmitter_model.dart';

class FramHeader {
  const FramHeader({
    required this.magic,
    required this.version,
    required this.totalSlots,
    required this.activeSlot,
    required this.usedBitmap,
  });

  final int magic;
  final int version;
  final int totalSlots;
  final int activeSlot;
  final int usedBitmap;
}

class FramCodec {
  static const magic = 0x54584346;
  static const version = 1;
  static const headerAddress = 0;
  static const headerSize = 32;
  static const modelsBase = 0x100;
  static const modelSlotSize = 64;
  static const modelBinarySize = 60;
  static const maxSlots = 16;

  static int slotAddress(int slot) {
    if (slot < 0 || slot >= maxSlots) throw RangeError.range(slot, 0, 15);
    return modelsBase + slot * modelSlotSize;
  }

  static FramHeader decodeHeader(Uint8List bytes) {
    if (bytes.length != headerSize) {
      throw const FormatException('Bad header size');
    }
    final data = ByteData.sublistView(bytes);
    return FramHeader(
      magic: data.getUint32(0, Endian.little),
      version: data.getUint16(4, Endian.little),
      totalSlots: data.getUint16(6, Endian.little),
      activeSlot: data.getUint16(8, Endian.little),
      usedBitmap: data.getUint32(10, Endian.little),
    );
  }

  static Uint8List encodeHeader(FramHeader header) {
    final bytes = Uint8List(headerSize);
    final data = ByteData.sublistView(bytes);
    data.setUint32(0, header.magic, Endian.little);
    data.setUint16(4, header.version, Endian.little);
    data.setUint16(6, header.totalSlots, Endian.little);
    data.setUint16(8, header.activeSlot, Endian.little);
    data.setUint32(10, header.usedBitmap, Endian.little);
    return bytes;
  }

  static TransmitterModel decodeModel(Uint8List slot) {
    if (slot.length < modelBinarySize) {
      throw const FormatException('Bad model size');
    }
    final bytes = Uint8List.sublistView(slot, 0, modelBinarySize);
    final data = ByteData.sublistView(bytes);
    final zero = bytes.take(16).toList().indexOf(0);
    final nameLength = zero < 0 ? 16 : zero;
    final name = utf8.decode(
      bytes.sublist(0, nameLength),
      allowMalformed: true,
    );
    var offset = 16;
    final bindCode = data.getUint16(offset, Endian.little);
    offset += 2;
    final rates = List.generate(4, (_) => data.getInt8(offset++));
    final expo = List.generate(4, (_) => data.getInt8(offset++));
    final drSwitch = data.getUint8(offset++);
    final activeRates = data.getUint8(offset++) != 0;
    final subtrim = List.generate(4, (_) {
      final value = data.getInt16(offset, Endian.little);
      offset += 2;
      return value;
    });
    final endpoints = List.generate(4, (_) {
      final low = data.getUint16(offset, Endian.little);
      final high = data.getUint16(offset + 2, Endian.little);
      offset += 4;
      return [low, high];
    });
    final reverseMask = data.getUint8(offset);
    offset += 6;
    final storedCrc = data.getUint16(offset, Endian.little);
    return TransmitterModel(
      name: name,
      bindCode: bindCode,
      rates: rates,
      expo: expo,
      drSwitch: drSwitch,
      activeRates: activeRates,
      subtrim: subtrim,
      endpoints: endpoints,
      reverse: List.generate(4, (index) => reverseMask & (1 << index) != 0),
      crcOk: storedCrc == crc16(Uint8List.sublistView(bytes, 0, 58)),
    );
  }

  static Uint8List encodeModel(TransmitterModel model) {
    _validate(model);
    final bytes = Uint8List(modelSlotSize);
    final data = ByteData.sublistView(bytes);
    final nameBytes = utf8.encode(model.name);
    final truncated = _truncateUtf8(nameBytes, 15);
    bytes.setRange(0, truncated.length, truncated);
    var offset = 16;
    data.setUint16(offset, model.bindCode & 0x7fff, Endian.little);
    offset += 2;
    for (final value in model.rates) {
      data.setInt8(offset++, value);
    }
    for (final value in model.expo) {
      data.setInt8(offset++, value);
    }
    data.setUint8(offset++, model.drSwitch & 0xff);
    data.setUint8(offset++, model.activeRates ? 1 : 0);
    for (final value in model.subtrim) {
      data.setInt16(offset, value, Endian.little);
      offset += 2;
    }
    for (final pair in model.endpoints) {
      data.setUint16(offset, pair[0], Endian.little);
      data.setUint16(offset + 2, pair[1], Endian.little);
      offset += 4;
    }
    var reverseMask = 0;
    for (var index = 0; index < 4; index++) {
      if (model.reverse[index]) reverseMask |= 1 << index;
    }
    data.setUint8(offset, reverseMask);
    offset += 6;
    data.setUint16(
      offset,
      crc16(Uint8List.sublistView(bytes, 0, 58)),
      Endian.little,
    );
    return bytes;
  }

  static void _validate(TransmitterModel model) {
    if (model.rates.length != 4 || model.rates.any((v) => v < 0 || v > 100)) {
      throw const FormatException('Rates must be between 0 and 100');
    }
    if (model.expo.length != 4 || model.expo.any((v) => v < -100 || v > 100)) {
      throw const FormatException('Expo must be between -100 and 100');
    }
    if (model.subtrim.length != 4 ||
        model.subtrim.any((v) => v < -500 || v > 500)) {
      throw const FormatException('Subtrim must be between -500 and 500');
    }
    if (model.endpoints.length != 4 ||
        model.endpoints.any(
          (p) => p.length != 2 || p[0] < 500 || p[1] > 2500 || p[0] >= p[1],
        )) {
      throw const FormatException(
        'Endpoints must be ordered and between 500 and 2500 µs',
      );
    }
    if (model.reverse.length != 4) {
      throw const FormatException('Four reverse flags required');
    }
  }

  static List<int> _truncateUtf8(List<int> value, int max) {
    var end = value.length.clamp(0, max);
    while (end > 0 && (value[end - 1] & 0xc0) == 0x80) {
      end--;
    }
    if (end > 0 &&
        utf8
            .decode(value.sublist(0, end), allowMalformed: true)
            .contains('\uFFFD')) {
      end--;
    }
    return value.sublist(0, end);
  }

  static int crc16(Uint8List bytes) {
    var crc = 0xffff;
    for (final byte in bytes) {
      crc ^= byte << 8;
      for (var bit = 0; bit < 8; bit++) {
        crc = (crc & 0x8000) != 0
            ? ((crc << 1) ^ 0x1021) & 0xffff
            : (crc << 1) & 0xffff;
      }
    }
    return crc;
  }
}
