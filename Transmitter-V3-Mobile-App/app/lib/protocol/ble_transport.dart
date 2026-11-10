import 'dart:async';
import 'dart:convert';

import 'package:flutter_blue_plus/flutter_blue_plus.dart';

import 'transmitter_transport.dart';

class BleTransport extends TransmitterTransport {
  static final serviceUuid = Guid('7d2a0001-8f45-4f3c-bc1d-5f91b7a6c301');
  static final commandUuid = Guid('7d2a0002-8f45-4f3c-bc1d-5f91b7a6c301');
  static final responseUuid = Guid('7d2a0003-8f45-4f3c-bc1d-5f91b7a6c301');

  BluetoothDevice? _device;
  BluetoothCharacteristic? _command;
  BluetoothCharacteristic? _response;
  StreamSubscription<List<int>>? _responseSubscription;
  Completer<String>? _pending;
  final StringBuffer _receiveBuffer = StringBuffer();

  @override
  bool get isConnected => _device?.isConnected ?? false;
  @override
  String get deviceName => _device?.platformName ?? '';

  @override
  Future<List<DiscoveredTransmitter>> scan() async {
    final found = <String, DiscoveredTransmitter>{};
    final subscription = FlutterBluePlus.onScanResults.listen((results) {
      for (final result in results) {
        final name = result.device.platformName.isEmpty
            ? result.advertisementData.advName
            : result.device.platformName;
        if (name.toLowerCase().contains('transmitter') ||
            result.advertisementData.serviceUuids.contains(serviceUuid)) {
          found[result.device.remoteId.str] = DiscoveredTransmitter(
            result.device.remoteId.str,
            name,
            result.device,
          );
        }
      }
    });
    try {
      await FlutterBluePlus.startScan(
        withServices: [serviceUuid],
        timeout: const Duration(seconds: 5),
      );
      await FlutterBluePlus.isScanning
          .where((value) => !value)
          .first
          .timeout(const Duration(seconds: 7));
    } finally {
      await subscription.cancel();
      await FlutterBluePlus.stopScan();
    }
    return found.values.toList();
  }

  @override
  Future<void> connect(DiscoveredTransmitter selected) async {
    final device = selected.nativeDevice as BluetoothDevice;
    // This project is currently a personal/noncommercial prototype. Revisit
    // the flutter_blue_plus license before any commercial distribution.
    await device.connect(
      license: License.nonprofit,
      timeout: const Duration(seconds: 12),
    );
    final services = await device.discoverServices();
    final service = services
        .where((item) => item.uuid == serviceUuid)
        .firstOrNull;
    if (service == null) {
      throw StateError('Transmitter configuration service not found');
    }
    _command = service.characteristics
        .where((item) => item.uuid == commandUuid)
        .firstOrNull;
    _response = service.characteristics
        .where((item) => item.uuid == responseUuid)
        .firstOrNull;
    if (_command == null || _response == null) {
      throw StateError('Incomplete transmitter BLE service');
    }
    await _response!.setNotifyValue(true);
    _responseSubscription = _response!.onValueReceived.listen(_onResponse);
    _device = device;
    if (await command('PING') != 'PONG') {
      throw StateError('Transmitter did not answer PING');
    }
  }

  void _onResponse(List<int> value) {
    _receiveBuffer.write(utf8.decode(value, allowMalformed: false));
    final text = _receiveBuffer.toString();
    final newline = text.indexOf('\n');
    if (newline >= 0) {
      final response = text.substring(0, newline).trim();
      final remaining = text.substring(newline + 1);
      _receiveBuffer.clear();
      _receiveBuffer.write(remaining);
      _pending?.complete(response);
      _pending = null;
    }
  }

  @override
  Future<String> command(String command) async {
    if (_command == null || _pending != null) {
      throw StateError('Transport busy or disconnected');
    }
    final completer = Completer<String>();
    _pending = completer;
    try {
      final bytes = utf8.encode('$command\n');
      final mtu = (_device?.mtuNow ?? 23) - 3;
      for (var offset = 0; offset < bytes.length; offset += mtu) {
        final end = (offset + mtu).clamp(0, bytes.length);
        await _command!.write(
          bytes.sublist(offset, end),
          withoutResponse: false,
        );
      }
      return await completer.future.timeout(const Duration(seconds: 4));
    } finally {
      if (identical(_pending, completer)) _pending = null;
    }
  }

  @override
  Future<void> disconnect() async {
    await _responseSubscription?.cancel();
    _responseSubscription = null;
    await _device?.disconnect();
    _device = null;
    _command = null;
    _response = null;
  }
}
