from __future__ import annotations

import base64
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import server


JPEG_1X1 = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////"
    "wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/"
    "9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAA"
    "AAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAA"
    "AAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/xAAU"
    "EQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EF//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EF//xAAU"
    "EAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EF//2Q=="
)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server.FRAME_STORE = server.FrameStore()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.DemoHandler)
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def read_json(self, path: str) -> tuple[int, dict[str, object]]:
        with urllib.request.urlopen(self.base_url + path, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_and_static_pages(self) -> None:
        status, payload = self.read_json("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        status, config = self.read_json("/api/config")
        self.assertEqual(status, 200)
        self.assertIn("/capture.html", config["capture_url"])
        with urllib.request.urlopen(self.base_url + "/viewer.html", timeout=3) as response:
            html = response.read().decode("utf-8")
        self.assertIn("Rokid Camera Link", html)

    def test_rejects_non_jpeg(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/api/frame",
            data=b"not-a-jpeg",
            method="POST",
            headers={"Content-Type": "image/jpeg"},
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(context.exception.code, 400)

    def test_accepts_raw_jpeg_and_serves_latest_frame(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/api/frame",
            data=JPEG_1X1,
            method="POST",
            headers={
                "Content-Type": "image/jpeg",
                "X-Device-Name": "unit-test-camera",
                "X-Frame-Width": "1",
                "X-Frame-Height": "1",
            },
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 202)
        self.assertTrue(payload["ok"])

        _, status = self.read_json("/api/status")
        self.assertTrue(status["has_frame"])
        self.assertEqual(status["frame"]["device_name"], "unit-test-camera")

        with urllib.request.urlopen(self.base_url + "/api/frame.jpg", timeout=3) as response:
            self.assertEqual(response.read(), JPEG_1X1)

    def test_accepts_existing_project_style_json(self) -> None:
        image = "data:image/jpeg;base64," + base64.b64encode(JPEG_1X1).decode("ascii")
        body = json.dumps(
            {
                "image": image,
                "width": 1,
                "height": 1,
                "device_name": "json-camera",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/api/frame",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["frame"]["device_name"], "json-camera")

    def test_analyze_endpoint_returns_shared_recognition_shape(self) -> None:
        original = server.analyze_jpeg
        server.analyze_jpeg = lambda jpeg: {
            "foods": [{"name": "白米饭", "estimated_weight_g": 120}],
            "quality": {"overall": 0.8},
            "guidance": "测试完成",
            "analyzer": "test",
            "model_name": "test",
        }
        try:
            request = urllib.request.Request(
                self.base_url + "/api/analyze",
                data=JPEG_1X1,
                method="POST",
                headers={
                    "Content-Type": "image/jpeg",
                    "X-Device-Name": "Rokid-RV101",
                },
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["foods"][0]["name"], "白米饭")
            self.assertEqual(payload["frame"]["device_name"], "Rokid-RV101")
        finally:
            server.analyze_jpeg = original


if __name__ == "__main__":
    unittest.main()
