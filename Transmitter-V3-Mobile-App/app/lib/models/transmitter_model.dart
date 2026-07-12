class TransmitterModel {
  TransmitterModel({
    required this.name,
    required this.bindCode,
    required this.rates,
    required this.expo,
    required this.drSwitch,
    required this.activeRates,
    required this.subtrim,
    required this.endpoints,
    required this.reverse,
    this.crcOk = true,
  });

  String name;
  int bindCode;
  List<int> rates;
  List<int> expo;
  int drSwitch;
  bool activeRates;
  List<int> subtrim;
  List<List<int>> endpoints;
  List<bool> reverse;
  bool crcOk;

  factory TransmitterModel.defaults([String name = 'New Model']) =>
      TransmitterModel(
        name: name,
        bindCode: 1,
        rates: [100, 100, 100, 100],
        expo: [0, 0, 0, 0],
        drSwitch: 0,
        activeRates: true,
        subtrim: [0, 0, 0, 0],
        endpoints: List.generate(4, (_) => [1000, 2000]),
        reverse: [false, false, false, false],
      );

  TransmitterModel copy() => TransmitterModel.fromJson(toJson());

  Map<String, dynamic> toJson() => {
    'name': name,
    'bind_code': bindCode,
    'rates': rates,
    'expo': expo,
    'dr_switch': drSwitch,
    'active_rates': activeRates,
    'subtrim': subtrim,
    'endpoints': endpoints,
    'reverse': reverse,
  };

  factory TransmitterModel.fromJson(Map<String, dynamic> json) {
    List<int> ints(String key, int count) {
      final value = json[key];
      if (value is! List || value.length != count) {
        throw FormatException('$key must contain $count values');
      }
      return value.map((item) => (item as num).toInt()).toList();
    }

    final endpointValue = json['endpoints'];
    if (endpointValue is! List || endpointValue.length != 4) {
      throw const FormatException('endpoints must contain four pairs');
    }
    final endpoints = endpointValue.map((pair) {
      if (pair is! List || pair.length != 2) {
        throw const FormatException('each endpoint must be a min/max pair');
      }
      return pair.map((item) => (item as num).toInt()).toList();
    }).toList();
    final reverseValue = json['reverse'];
    if (reverseValue is! List || reverseValue.length != 4) {
      throw const FormatException('reverse must contain four flags');
    }
    return TransmitterModel(
      name: json['name'] as String? ?? 'Imported Model',
      bindCode: (json['bind_code'] as num?)?.toInt() ?? 1,
      rates: ints('rates', 4),
      expo: ints('expo', 4),
      drSwitch: (json['dr_switch'] as num?)?.toInt() ?? 0,
      activeRates: json['active_rates'] as bool? ?? true,
      subtrim: ints('subtrim', 4),
      endpoints: endpoints,
      reverse: reverseValue.map((item) => item as bool).toList(),
    );
  }
}
