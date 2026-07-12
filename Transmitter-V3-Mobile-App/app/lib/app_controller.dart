import 'dart:convert';

import 'package:flutter/foundation.dart';

import 'models/transmitter_model.dart';
import 'protocol/fram_codec.dart';
import 'protocol/transmitter_transport.dart';

class SlotSummary {
  SlotSummary(this.index, {this.used = false, this.active = false, this.model});
  final int index;
  bool used;
  bool active;
  TransmitterModel? model;
}

class AppController extends ChangeNotifier {
  AppController(this.transport);
  final TransmitterTransport transport;
  bool busy = false;
  String? error;
  String info = '';
  List<DiscoveredTransmitter> devices = [];
  List<SlotSummary> slots = List.generate(FramCodec.maxSlots, SlotSummary.new);

  bool get connected => transport.isConnected;

  Future<void> _run(Future<void> Function() action) async {
    busy = true;
    error = null;
    notifyListeners();
    try {
      await action();
    } catch (exception) {
      error = exception.toString().replaceFirst('Exception: ', '');
      rethrow;
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  Future<void> scan() => _run(() async {
    devices = await transport.scan();
  });

  Future<void> connect(DiscoveredTransmitter device) => _run(() async {
    await transport.connect(device);
    info = await transport.command('INFO');
    await _refreshInternal();
  });

  Future<void> disconnect() => _run(() async {
    await transport.disconnect();
    devices = [];
    slots = List.generate(FramCodec.maxSlots, SlotSummary.new);
  });

  Future<void> refresh() => _run(_refreshInternal);

  Future<void> _refreshInternal() async {
    final header = FramCodec.decodeHeader(
      await transport.read(FramCodec.headerAddress, FramCodec.headerSize),
    );
    if (header.magic != FramCodec.magic ||
        header.version != FramCodec.version) {
      throw StateError('Unsupported or uninitialized transmitter FRAM');
    }
    slots = List.generate(FramCodec.maxSlots, (index) {
      final used = header.usedBitmap & (1 << index) != 0;
      return SlotSummary(index, used: used, active: index == header.activeSlot);
    });
    for (final slot in slots.where((item) => item.used)) {
      slot.model = FramCodec.decodeModel(
        await transport.read(
          FramCodec.slotAddress(slot.index),
          FramCodec.modelSlotSize,
        ),
      );
    }
  }

  Future<void> save(int slotIndex, TransmitterModel model) => _run(() async {
    final encoded = FramCodec.encodeModel(model);
    await transport.write(FramCodec.slotAddress(slotIndex), encoded);
    final verify = await transport.read(
      FramCodec.slotAddress(slotIndex),
      FramCodec.modelSlotSize,
    );
    if (!listEquals(encoded, verify)) {
      throw StateError('Read-back verification failed');
    }

    final old = FramCodec.decodeHeader(
      await transport.read(0, FramCodec.headerSize),
    );
    final header = FramHeader(
      magic: old.magic,
      version: old.version,
      totalSlots: old.totalSlots,
      activeSlot: old.activeSlot,
      usedBitmap: old.usedBitmap | (1 << slotIndex),
    );
    final headerBytes = FramCodec.encodeHeader(header);
    await transport.write(0, headerBytes);
    if (!listEquals(
      headerBytes,
      await transport.read(0, FramCodec.headerSize),
    )) {
      throw StateError('Header verification failed');
    }
    await _refreshInternal();
  });

  Future<void> setActive(int slotIndex) => _run(() async {
    if (!slots[slotIndex].used) {
      throw StateError('Cannot activate an empty slot');
    }
    final old = FramCodec.decodeHeader(
      await transport.read(0, FramCodec.headerSize),
    );
    final bytes = FramCodec.encodeHeader(
      FramHeader(
        magic: old.magic,
        version: old.version,
        totalSlots: old.totalSlots,
        activeSlot: slotIndex,
        usedBitmap: old.usedBitmap,
      ),
    );
    await transport.write(0, bytes);
    if (!listEquals(bytes, await transport.read(0, FramCodec.headerSize))) {
      throw StateError('Active-model verification failed');
    }
    await _refreshInternal();
  });

  Future<void> delete(int slotIndex) => _run(() async {
    final old = FramCodec.decodeHeader(
      await transport.read(0, FramCodec.headerSize),
    );
    if (old.activeSlot == slotIndex) {
      throw StateError('Select another active model before deleting this one');
    }
    await transport.write(
      FramCodec.slotAddress(slotIndex),
      Uint8List(FramCodec.modelSlotSize),
    );
    final bytes = FramCodec.encodeHeader(
      FramHeader(
        magic: old.magic,
        version: old.version,
        totalSlots: old.totalSlots,
        activeSlot: old.activeSlot,
        usedBitmap: old.usedBitmap & ~(1 << slotIndex),
      ),
    );
    await transport.write(0, bytes);
    await _refreshInternal();
  });

  String exportJson(TransmitterModel model) =>
      const JsonEncoder.withIndent('  ').convert(model.toJson());
  TransmitterModel importJson(String text) =>
      TransmitterModel.fromJson(jsonDecode(text) as Map<String, dynamic>);
}
