import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.routes import admin
from app.services import amap_service

class AreaEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = amap_service.CAMPUS_AREAS
        self.patch = patch.object(admin, "CONFIG_FILE", Path(self.temp.name) / "areas.json")
        self.patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        amap_service.CAMPUS_AREAS = self.old
        self.patch.stop()
        self.temp.cleanup()

    def test_rectangle_roundtrip_and_boundary(self):
        area = {"type":"rectangle", "location":"0,0", "radius":500,
                "bounds":[[103.93,30.75],[103.94,30.76]]}
        response = self.client.post("/api/admin/areas", json={"areas":{"学校食堂":area}})
        self.assertEqual(response.status_code, 200)
        stored = response.json()["areas"]["学校食堂"]
        self.assertEqual(stored["bounds"], area["bounds"])
        self.assertEqual(stored["location"], "103.935000,30.755000")
        self.assertGreater(stored["radius"], 500)
        self.assertEqual(self.client.get("/api/admin/areas").json(), response.json())
        with patch.object(amap_service, "CONFIG_FILE", admin.CONFIG_FILE):
            self.assertEqual(amap_service.load_campus_areas()["学校食堂"], stored)
        self.assertTrue(amap_service.within_boundary({"location":"103.935,30.755"}, stored))
        self.assertFalse(amap_service.within_boundary({"location":"103.929,30.755"}, stored))

    def test_invalid_geometry_does_not_write(self):
        for location in ("nan,30", "181,30", "103,91", "broken"):
            r = self.client.post("/api/admin/areas", json={"areas":{"南门":{"location":location,"radius":500}}})
            self.assertEqual(r.status_code,422)
        self.assertFalse(admin.CONFIG_FILE.exists())

    def test_invalid_name_and_empty(self):
        for areas in ({}, {"随意区域":{"location":"103,30","radius":500}}):
            self.assertEqual(self.client.post("/api/admin/areas",json={"areas":areas}).status_code,422)

    def test_editor_and_public_map_settings(self):
        response = self.client.get("/area-config")
        self.assertEqual(response.status_code,200)
        self.assertIn("/api/admin/areas",response.text)
        self.assertEqual(set(self.client.get("/api/admin/map-config").json()), {"key","securityJsCode"})

    def test_circle_boundary(self):
        config = {"location":"103.93,30.75","radius":100}
        self.assertTrue(amap_service.within_boundary({"location":"103.93,30.75"},config))
        self.assertFalse(amap_service.within_boundary({"location":"103.94,30.75"},config))

    def test_overlap_assignment_independent_of_query_order(self):
        configs = {"学校食堂":{"location":"103,30","radius":1000},
                   "南门":{"location":"103.005,30","radius":500}}
        poi = {"location":"103.005,30"}
        self.assertEqual(amap_service.area_owner(poi,configs),"南门")
        self.assertEqual(amap_service.area_owner(poi,dict(reversed(list(configs.items())))),"南门")

    def test_polygon_excludes_bounding_circle_corners(self):
        area = {"type":"polygon","location":"103,30","radius":500,
                "path":[[103,30],[103.01,30],[103.005,30.01]]}
        r = self.client.post("/api/admin/areas",json={"areas":{"学校食堂":area}})
        self.assertEqual(r.status_code,200)
        stored = r.json()["areas"]["学校食堂"]
        self.assertEqual(stored["path"],area["path"])
        self.assertTrue(amap_service.within_boundary({"location":"103.005,30.005"},stored))
        self.assertFalse(amap_service.within_boundary({"location":"103.001,30.009"},stored))
