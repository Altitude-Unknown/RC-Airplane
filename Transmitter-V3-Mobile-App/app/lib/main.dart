import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';

import 'app_controller.dart';
import 'models/transmitter_model.dart';
import 'protocol/ble_transport.dart';
import 'protocol/transmitter_transport.dart';

void main() => runApp(const TransmitterConfiguratorApp());

class TransmitterConfiguratorApp extends StatefulWidget {
  const TransmitterConfiguratorApp({super.key, this.transport});
  final TransmitterTransport? transport;
  @override
  State<TransmitterConfiguratorApp> createState() =>
      _TransmitterConfiguratorAppState();
}

class _TransmitterConfiguratorAppState
    extends State<TransmitterConfiguratorApp> {
  late final AppController controller = AppController(
    widget.transport ?? BleTransport(),
  )..addListener(_changed);
  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    controller.removeListener(_changed);
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'Transmitter Configurator',
    theme: ThemeData(
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff0f7f8f)),
      useMaterial3: true,
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
      ),
    ),
    home: HomeScreen(controller: controller),
  );
}

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key, required this.controller});
  final AppController controller;

  Future<void> _safe(
    BuildContext context,
    Future<void> Function() action,
  ) async {
    try {
      await action();
    } catch (_) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(controller.error ?? 'Operation failed')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Walach Aviation Tx V3'),
      actions: [
        if (controller.connected)
          IconButton(
            onPressed: controller.busy
                ? null
                : () => _safe(context, controller.refresh),
            icon: const Icon(Icons.refresh),
          ),
        IconButton(
          onPressed: controller.busy
              ? null
              : () => _safe(
                  context,
                  controller.connected
                      ? controller.disconnect
                      : controller.scan,
                ),
          icon: Icon(
            controller.connected
                ? Icons.bluetooth_connected
                : Icons.bluetooth_searching,
          ),
        ),
      ],
    ),
    body: Stack(
      children: [
        if (!controller.connected)
          _ConnectView(
            controller: controller,
            safe: (action) => _safe(context, action),
          )
        else
          _ModelList(
            controller: controller,
            safe: (action) => _safe(context, action),
          ),
        if (controller.busy) const LinearProgressIndicator(),
      ],
    ),
  );
}

class _ConnectView extends StatelessWidget {
  const _ConnectView({required this.controller, required this.safe});
  final AppController controller;
  final void Function(Future<void> Function()) safe;
  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.all(24),
    children: [
      const Icon(Icons.flight, size: 72),
      const SizedBox(height: 16),
      Text(
        'Connect to Transmitter V3',
        style: Theme.of(context).textTheme.headlineSmall,
        textAlign: TextAlign.center,
      ),
      const SizedBox(height: 8),
      const Text(
        'Put the transmitter in wireless configuration mode before scanning.',
        textAlign: TextAlign.center,
      ),
      const SizedBox(height: 24),
      FilledButton.icon(
        onPressed: controller.busy ? null : () => safe(controller.scan),
        icon: const Icon(Icons.bluetooth_searching),
        label: const Text('Scan for transmitters'),
      ),
      const SizedBox(height: 16),
      ...controller.devices.map(
        (device) => Card(
          child: ListTile(
            leading: const Icon(Icons.settings_remote),
            title: Text(device.name.isEmpty ? 'Transmitter V3' : device.name),
            subtitle: Text(device.id),
            trailing: const Icon(Icons.chevron_right),
            onTap: controller.busy
                ? null
                : () => safe(() => controller.connect(device)),
          ),
        ),
      ),
    ],
  );
}

class _ModelList extends StatelessWidget {
  const _ModelList({required this.controller, required this.safe});
  final AppController controller;
  final void Function(Future<void> Function()) safe;
  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.all(12),
    children: [
      Card(
        child: ListTile(
          leading: const Icon(Icons.bluetooth_connected),
          title: Text(controller.transport.deviceName),
          subtitle: Text(controller.info),
        ),
      ),
      ...controller.slots.map(
        (slot) => Card(
          child: ListTile(
            leading: CircleAvatar(child: Text('${slot.index + 1}')),
            title: Text(slot.model?.name ?? 'Empty slot'),
            subtitle: Text(
              slot.active
                  ? 'Active model'
                  : slot.model?.crcOk == false
                  ? 'CRC error — do not use'
                  : slot.used
                  ? 'Ready'
                  : 'Tap to create',
            ),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (slot.active)
                  const Icon(Icons.check_circle, color: Colors.green),
                if (slot.model?.crcOk == false)
                  const Icon(Icons.warning, color: Colors.red),
                const Icon(Icons.chevron_right),
              ],
            ),
            onTap: () async {
              final model =
                  slot.model?.copy() ??
                  TransmitterModel.defaults('Model ${slot.index + 1}');
              final saved = await Navigator.push<bool>(
                context,
                MaterialPageRoute(
                  builder: (_) => ModelEditor(
                    controller: controller,
                    slot: slot,
                    model: model,
                  ),
                ),
              );
              if (saved == true) safe(controller.refresh);
            },
          ),
        ),
      ),
    ],
  );
}

class ModelEditor extends StatefulWidget {
  const ModelEditor({
    super.key,
    required this.controller,
    required this.slot,
    required this.model,
  });
  final AppController controller;
  final SlotSummary slot;
  final TransmitterModel model;
  @override
  State<ModelEditor> createState() => _ModelEditorState();
}

class _ModelEditorState extends State<ModelEditor> {
  static const names = ['Rudder', 'Aileron', 'Elevator', 'Throttle'];
  late TransmitterModel model = widget.model;
  late final nameController = TextEditingController(text: model.name);
  late final bindController = TextEditingController(text: '${model.bindCode}');

  int _number(String value, String label) {
    final number = int.tryParse(value);
    if (number == null) throw FormatException('$label must be a whole number');
    return number;
  }

  Future<void> _save() async {
    model.name = nameController.text.trim();
    model.bindCode = _number(bindController.text, 'Bind code');
    try {
      await widget.controller.save(widget.slot.index, model);
      if (mounted) Navigator.pop(context, true);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(widget.controller.error ?? 'Save failed')),
        );
      }
    }
  }

  Future<void> _export() async {
    final json = widget.controller.exportJson(model);
    await SharePlus.instance.share(
      ShareParams(
        files: [
          XFile.fromData(
            utf8.encode(json),
            mimeType: 'application/json',
            name: '${model.name.replaceAll(' ', '_')}.json',
          ),
        ],
        subject: model.name,
      ),
    );
  }

  Future<void> _import() async {
    try {
      final clipboard = await Clipboard.getData(Clipboard.kTextPlain);
      final text = clipboard?.text;
      if (text == null || text.trim().isEmpty) {
        throw const FormatException('Clipboard does not contain model JSON');
      }
      final imported = widget.controller.importJson(text);
      setState(() {
        model = imported;
        nameController.text = model.name;
        bindController.text = '${model.bindCode}';
      });
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Import failed: $error')));
      }
    }
  }

  Widget _intField(String label, int value, ValueChanged<int> changed) =>
      Expanded(
        child: TextFormField(
          initialValue: '$value',
          keyboardType: const TextInputType.numberWithOptions(signed: true),
          decoration: InputDecoration(labelText: label),
          onChanged: (text) {
            final parsed = int.tryParse(text);
            if (parsed != null) changed(parsed);
          },
        ),
      );

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text('Model ${widget.slot.index + 1}'),
      actions: [
        IconButton(
          tooltip: 'Import model JSON from clipboard',
          onPressed: _import,
          icon: const Icon(Icons.content_paste),
        ),
        IconButton(onPressed: _export, icon: const Icon(Icons.share)),
      ],
    ),
    body: ListView(
      padding: const EdgeInsets.all(16),
      children: [
        TextField(
          controller: nameController,
          maxLength: 15,
          decoration: const InputDecoration(labelText: 'Model name'),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: bindController,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(labelText: 'Bind code (0–32767)'),
        ),
        const SizedBox(height: 12),
        SwitchListTile(
          title: const Text('Use high rates'),
          value: model.activeRates,
          onChanged: (value) => setState(() => model.activeRates = value),
        ),
        ...List.generate(
          4,
          (index) => Card(
            child: ExpansionTile(
              title: Text(names[index]),
              subtitle: Text(
                'Rate ${model.rates[index]}% • Expo ${model.expo[index]}%',
              ),
              childrenPadding: const EdgeInsets.all(12),
              children: [
                Row(
                  children: [
                    _intField(
                      'Rate %',
                      model.rates[index],
                      (v) => model.rates[index] = v,
                    ),
                    const SizedBox(width: 8),
                    _intField(
                      'Expo %',
                      model.expo[index],
                      (v) => model.expo[index] = v,
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    _intField(
                      'Subtrim µs',
                      model.subtrim[index],
                      (v) => model.subtrim[index] = v,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Reverse'),
                        value: model.reverse[index],
                        onChanged: (v) =>
                            setState(() => model.reverse[index] = v),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    _intField(
                      'Minimum µs',
                      model.endpoints[index][0],
                      (v) => model.endpoints[index][0] = v,
                    ),
                    const SizedBox(width: 8),
                    _intField(
                      'Maximum µs',
                      model.endpoints[index][1],
                      (v) => model.endpoints[index][1] = v,
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: widget.controller.busy ? null : _save,
          icon: const Icon(Icons.save),
          label: const Text('Save and verify'),
        ),
        if (widget.slot.used && !widget.slot.active)
          TextButton.icon(
            onPressed: () async {
              await widget.controller.setActive(widget.slot.index);
              if (!context.mounted) return;
              Navigator.pop(context, true);
            },
            icon: const Icon(Icons.check_circle),
            label: const Text('Make active model'),
          ),
        if (widget.slot.used && !widget.slot.active)
          TextButton.icon(
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            onPressed: () async {
              await widget.controller.delete(widget.slot.index);
              if (!context.mounted) return;
              Navigator.pop(context, true);
            },
            icon: const Icon(Icons.delete),
            label: const Text('Delete model'),
          ),
      ],
    ),
  );
}
