import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

abstract class TransmitterTransport {
  bool get isConnected;
  String get deviceName;
  Future<List<DiscoveredTransmitter>> scan();
  Future<void> connect(DiscoveredTransmitter device);
  Future<void> disconnect();
  Future<String> command(String command);

  Future<Uint8List> read(int address, int length) async {
    final response = await command('READ $address $length');
    if (!response.startsWith('DATA ')) {
      throw StateError('Unexpected response: $response');
    }
    final text = response.substring(5).replaceAll(' ', '');
    if (text.length != length * 2) throw StateError('Incomplete response');
    return Uint8List.fromList(
      List.generate(
        length,
        (index) =>
            int.parse(text.substring(index * 2, index * 2 + 2), radix: 16),
      ),
    );
  }

  Future<void> write(int address, Uint8List bytes) async {
    final hex = bytes
        .map((value) => value.toRadixString(16).padLeft(2, '0'))
        .join()
        .toUpperCase();
    final response = await command('WRITE $address $hex');
    if (response != 'OK') throw StateError('Write failed: $response');
  }
}

class DiscoveredTransmitter {
  const DiscoveredTransmitter(this.id, this.name, this.nativeDevice);
  final String id;
  final String name;
  final Object nativeDevice;
}

class MockTransmitterTransport extends TransmitterTransport {
  final _fram = Uint8List(32768);
  bool _connected = false;

  @override
  bool get isConnected => _connected;
  @override
  String get deviceName => _connected ? 'Demo Transmitter V3' : '';
  @override
  Future<List<DiscoveredTransmitter>> scan() async => [
    DiscoveredTransmitter('demo', 'Demo Transmitter V3', Object()),
  ];
  @override
  Future<void> connect(DiscoveredTransmitter device) async => _connected = true;
  @override
  Future<void> disconnect() async => _connected = false;
  @override
  Future<String> command(String command) async {
    if (!_connected) throw StateError('Not connected');
    if (command == 'PING') return 'PONG';
    if (command == 'INFO') {
      return '{"mcu":"DEMO","fram_size":32768,"proto":"1.0","role":"TX"}';
    }
    if (command == 'RANGE') return 'RANGE 32768';
    final parts = command.split(' ');
    if (parts[0] == 'READ') {
      final address = int.parse(parts[1]);
      final length = int.parse(parts[2]);
      return 'DATA ${_fram.sublist(address, address + length).map((v) => v.toRadixString(16).padLeft(2, '0')).join().toUpperCase()}';
    }
    if (parts[0] == 'WRITE') {
      final address = int.parse(parts[1]);
      final data = base64Decode(
        base64Encode(
          List.generate(
            parts[2].length ~/ 2,
            (i) => int.parse(parts[2].substring(i * 2, i * 2 + 2), radix: 16),
          ),
        ),
      );
      _fram.setRange(address, address + data.length, data);
      return 'OK';
    }
    return 'ERR';
  }
}
