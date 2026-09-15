"""Aircraft settings codec coverage for the configurator."""
import unittest
from test_gui_model_codec import MemoryWorker
from fram_gui_models import ModelsStore

class AircraftCodecTests(unittest.TestCase):
    def test_codec_aircraft_types(self):
        store = ModelsStore(MemoryWorker())
        for kind in range(3):
            model = dict(name='Plane', bind_code=1, rates=[100]*4, expo=[0]*4,
                         dr_switch=0, active_rates=False, subtrim=[0]*4,
                         endpoints=[[1000,2000] for _ in range(4)], aircraft_type=kind,
                         vtail_rudder_reverse=bool(kind))
            store.write_model(0, model)
            decoded = store.read_model(0)
            self.assertEqual(decoded['aircraft_type'], kind)
            self.assertTrue(decoded['crc_ok'])
            self.assertEqual(decoded['vtail_rudder_reverse'], bool(kind))
        model['aircraft_type'] = 3
        with self.assertRaises(ValueError):
            store.write_model(0, model)


if __name__ == "__main__":
    unittest.main()
