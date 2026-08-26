import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

MODULE_PATH = Path(__file__).resolve().parents[1] / "collector.py"
spec = importlib.util.spec_from_file_location("collector", MODULE_PATH)
collector = importlib.util.module_from_spec(spec)
sys.modules["collector"] = collector
spec.loader.exec_module(collector)

SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Folder>
<Placemark><name>Example Paddler</name><ExtendedData>
<Data name="Time UTC"><value>8/25/2026 11:50:00 PM</value></Data>
<Data name="Name"><value>Example Paddler</value></Data>
<Data name="Map Display Name"><value>Example Paddle</value></Data>
<Data name="Device Type"><value>inReach Mini 2</value></Data>
<Data name="IMEI"><value>300000000000000</value></Data>
<Data name="Latitude"><value>34.420123</value></Data>
<Data name="Longitude"><value>-119.698456</value></Data>
<Data name="Elevation"><value>3.05 m from MSL</value></Data>
<Data name="Velocity"><value>5.0 km/h</value></Data>
<Data name="Course"><value>270.00 \xc2\xb0 True</value></Data>
<Data name="Valid GPS Fix"><value>True</value></Data>
<Data name="In Emergency"><value>False</value></Data>
<Data name="Text"><value>private message should not survive</value></Data>
<Data name="Event"><value>Tracking message received.</value></Data>
</ExtendedData><Point><coordinates>-119.698456,34.420123,3.05</coordinates></Point></Placemark>
<Placemark><name>track line</name><LineString><coordinates>-119.7,34.4,0</coordinates></LineString></Placemark>
</Folder></Document></kml>"""

SAMPLE_TRACK = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Folder>
<Placemark><ExtendedData>
<Data name="Time UTC"><value>8/25/2026 11:35:00 PM</value></Data>
<Data name="Latitude"><value>34.410001</value></Data><Data name="Longitude"><value>-119.710001</value></Data>
<Data name="Velocity"><value>4.0 km/h</value></Data><Data name="Course"><value>250 True</value></Data>
<Data name="Valid GPS Fix"><value>True</value></Data><Data name="Text"><value>do not retain</value></Data>
</ExtendedData><Point><coordinates>-119.710001,34.410001,0</coordinates></Point></Placemark>
<Placemark><ExtendedData>
<Data name="Time UTC"><value>8/25/2026 11:45:00 PM</value></Data>
<Data name="Latitude"><value>34.415002</value></Data><Data name="Longitude"><value>-119.704002</value></Data>
<Data name="Velocity"><value>4.5 km/h</value></Data><Data name="Course"><value>260 True</value></Data>
<Data name="Valid GPS Fix"><value>True</value></Data>
</ExtendedData><Point><coordinates>-119.704002,34.415002,0</coordinates></Point></Placemark>
<Placemark><ExtendedData>
<Data name="Time UTC"><value>8/25/2026 11:50:00 PM</value></Data>
<Data name="Latitude"><value>34.420123</value></Data><Data name="Longitude"><value>-119.698456</value></Data>
<Data name="Velocity"><value>5.0 km/h</value></Data><Data name="Course"><value>270 True</value></Data>
<Data name="Valid GPS Fix"><value>True</value></Data>
</ExtendedData><Point><coordinates>-119.698456,34.420123,0</coordinates></Point></Placemark>
</Folder></Document></kml>"""


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.entry = {
            "id": "example",
            "name": "Example",
            "activity": "SUP",
            "feed_id": "example",
            "opt_in_exact": False,
        }
        self.now = datetime(2026, 8, 25, 23, 55, tzinfo=timezone.utc)

    def test_parse_point_and_ignore_track_line(self):
        points = collector.parse_kml(SAMPLE)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["Device Type"], "inReach Mini 2")
        self.assertEqual(points[0]["Latitude"], "34.420123")

    def test_normalize_converts_imperial_and_coarsens_position(self):
        point = collector.parse_kml(SAMPLE)[0]
        item = collector.normalize(self.entry, point, self.now)
        self.assertEqual(item["status"], "LIVE")
        self.assertEqual(item["lat"], 34.420)
        self.assertEqual(item["lng"], -119.698)
        self.assertEqual(item["position_precision"], "coarse-prototype")
        self.assertEqual(item["elevation_ft"], 10)
        self.assertEqual(item["speed_mph"], 3.1)
        self.assertEqual(item["heading_deg_true"], 270.0)
        self.assertNotIn("IMEI", item)
        self.assertNotIn("Text", item)
        self.assertNotIn("In Emergency", item)

    def test_exact_coordinates_require_opt_in(self):
        point = collector.parse_kml(SAMPLE)[0]
        entry = dict(self.entry, opt_in_exact=True)
        item = collector.normalize(entry, point, self.now)
        self.assertEqual(item["lat"], 34.420123)
        self.assertEqual(item["lng"], -119.698456)
        self.assertEqual(item["position_precision"], "exact-opt-in")

    def test_breadcrumbs_require_separate_explicit_opt_in(self):
        points = collector.parse_kml(SAMPLE_TRACK)
        no_consent = collector.normalized_breadcrumbs(dict(self.entry, opt_in_exact=True), points, self.now)
        self.assertEqual(no_consent, [])
        consented = collector.normalized_breadcrumbs(
            dict(self.entry, opt_in_exact=True, opt_in_breadcrumbs=True), points, self.now
        )
        self.assertEqual(len(consented), 3)
        self.assertEqual(consented[0]["lat"], 34.410001)
        self.assertEqual(consented[-1]["lng"], -119.698456)
        for breadcrumb in consented:
            self.assertNotIn("Text", breadcrumb)
            self.assertNotIn("IMEI", breadcrumb)
            self.assertNotIn("event", breadcrumb)

    def test_breadcrumbs_are_chronological_and_limited_to_recent_window(self):
        points = collector.parse_kml(SAMPLE_TRACK)
        consented = collector.normalized_breadcrumbs(
            dict(self.entry, opt_in_exact=True, opt_in_breadcrumbs=True), points, self.now,
            max_points=2, max_age_hours=12
        )
        self.assertEqual(len(consented), 2)
        self.assertLess(consented[0]["time_utc"], consented[1]["time_utc"])

    def test_tracking_off_overrides_freshness(self):
        point = collector.parse_kml(SAMPLE)[0]
        point["Event"] = "Tracking turned off from device."
        status, age = collector.freshness_status(point, self.now)
        self.assertEqual(status, "STOPPED")
        self.assertEqual(age, 5.0)

    def test_freshness_thresholds(self):
        point = collector.parse_kml(SAMPLE)[0]
        status, _ = collector.freshness_status(point, datetime(2026, 8, 26, 0, 10, tzinfo=timezone.utc))
        self.assertEqual(status, "AGING")
        status, _ = collector.freshness_status(point, datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc))
        self.assertEqual(status, "STALE")


if __name__ == "__main__":
    unittest.main()
