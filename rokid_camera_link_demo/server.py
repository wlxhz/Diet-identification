from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import socket
import sys
import threading
import time
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
MAX_FRAME_BYTES = 8 * 1024 * 1024
PROJECT_ROOT = ROOT.parent
HEALTH_APP_ROOT = PROJECT_ROOT / "health_diet_app"


def analyze_jpeg(jpeg: bytes) -> dict[str, object]:
    """Run the shared recognizer lazily so camera-only mode stays lightweight."""
    health_root = str(HEALTH_APP_ROOT)
    if health_root not in sys.path:
        sys.path.insert(0, health_root)
    try:
        from recognition_adapter import RecognitionUnavailable, analyze_image
    except ImportError as exc:
        raise RuntimeError("无法加载健康应用识别适配层") from exc

    data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
    try:
        return analyze_image(data_url)
    except RecognitionUnavailable as exc:
        raise RuntimeError(str(exc)) from exc


@dataclass
class FrameMetadata:
    sequence: int = 0
    received_at_ms: int = 0
    device_name: str = ""
    client_ip: str = ""
    content_type: str = "image/jpeg"
    size_bytes: int = 0
    width: int = 0
    height: int = 0


class FrameStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._metadata = FrameMetadata()

    def put(
        self,
        jpeg: bytes,
        *,
        device_name: str,
        client_ip: str,
        width: int,
        height: int,
    ) -> FrameMetadata:
        with self._lock:
            sequence = self._metadata.sequence + 1
            self._jpeg = jpeg
            self._metadata = FrameMetadata(
                sequence=sequence,
                received_at_ms=int(time.time() * 1000),
                device_name=device_name[:100] or "unknown-device",
                client_ip=client_ip,
                size_bytes=len(jpeg),
                width=max(0, width),
                height=max(0, height),
            )
            return FrameMetadata(**asdict(self._metadata))

    def get(self) -> tuple[bytes | None, FrameMetadata]:
        with self._lock:
            jpeg = self._jpeg
            metadata = FrameMetadata(**asdict(self._metadata))
        return jpeg, metadata


FRAME_STORE = FrameStore()


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def parse_positive_int(value: str | None) -> int:
    try:
        return max(0, int(value or "0"))
    except ValueError:
        return 0


def decode_frame_body(content_type: str, body: bytes) -> tuple[bytes, dict[str, object]]:
    if content_type.startswith("application/json"):
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON 请求体无法解析") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON 请求体必须是对象")
        image = payload.get("image")
        if not isinstance(image, str) or not image:
            raise ValueError("JSON 中缺少 image")
        encoded = image.split(",", 1)[1] if "," in image else image
        try:
            jpeg = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("image 不是有效的 Base64") from exc
        return jpeg, payload
    return body, {}


def is_jpeg(data: bytes) -> bool:
    return len(data) >= 4 and data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "RokidCameraDemo/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {self.client_address[0]} {format % args}")

    def _send_bytes(
        self,
        status: HTTPStatus | int,
        body: bytes,
        content_type: str,
        *,
        cache_control: str = "no-store",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: HTTPStatus | int, payload: object) -> None:
        self._send_bytes(status, json_bytes(payload), "application/json; charset=utf-8")

    def _read_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("缺少 Content-Length")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length 无效") from exc
        if length <= 0:
            raise ValueError("请求体为空")
        if length > MAX_FRAME_BYTES:
            raise OverflowError(f"图片超过 {MAX_FRAME_BYTES // (1024 * 1024)}MB 限制")
        return self.rfile.read(length)

    def _serve_static(self, relative_path: str) -> None:
        allowed = {
            "viewer.html",
            "capture.html",
            "styles.css",
            "viewer.js",
            "capture.js",
        }
        if relative_path not in allowed:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        file_path = STATIC_ROOT / relative_path
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self._send_bytes(
            HTTPStatus.OK,
            file_path.read_bytes(),
            content_type,
            cache_control="no-cache",
        )

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Device-Name, X-Frame-Width, X-Frame-Height",
        )
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/viewer.html")
            self.end_headers()
            return
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "service": "rokid-camera-link-demo"})
            return
        if path == "/api/config":
            lan_ip = guess_lan_ip()
            port = self.server.server_port
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "lan_ip": lan_ip,
                    "port": port,
                    "capture_url": f"http://{lan_ip}:{port}/capture.html",
                    "upload_url": f"http://{lan_ip}:{port}/api/frame",
                },
            )
            return
        if path == "/api/status":
            jpeg, metadata = FRAME_STORE.get()
            now_ms = int(time.time() * 1000)
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "has_frame": jpeg is not None,
                    "frame": asdict(metadata),
                    "age_ms": max(0, now_ms - metadata.received_at_ms)
                    if metadata.received_at_ms
                    else None,
                },
            )
            return
        if path == "/api/frame.jpg":
            jpeg, metadata = FRAME_STORE.get()
            if jpeg is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "尚未收到图片"})
                return
            self._send_bytes(
                HTTPStatus.OK,
                jpeg,
                "image/jpeg",
                extra_headers={
                    "X-Frame-Sequence": str(metadata.sequence),
                    "X-Received-At-Ms": str(metadata.received_at_ms),
                },
            )
            return
        relative_path = path.removeprefix("/")
        self._serve_static(relative_path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/frame", "/api/analyze"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            body = self._read_body()
            content_type = self.headers.get("Content-Type", "application/octet-stream")
            jpeg, payload = decode_frame_body(content_type, body)
            if len(jpeg) > MAX_FRAME_BYTES:
                raise OverflowError(f"解码后图片超过 {MAX_FRAME_BYTES // (1024 * 1024)}MB 限制")
            if not is_jpeg(jpeg):
                raise ValueError("请求体不是有效的 JPEG 图片")
            device_name = str(
                payload.get("device_name")
                or self.headers.get("X-Device-Name")
                or "unknown-device"
            )
            width = parse_positive_int(
                str(payload.get("width") or self.headers.get("X-Frame-Width") or "0")
            )
            height = parse_positive_int(
                str(payload.get("height") or self.headers.get("X-Frame-Height") or "0")
            )
            metadata = FRAME_STORE.put(
                jpeg,
                device_name=device_name,
                client_ip=self.client_address[0],
                width=width,
                height=height,
            )
            if path == "/api/analyze":
                analysis = analyze_jpeg(jpeg)
                self._send_json(
                    HTTPStatus.OK,
                    {"ok": True, "frame": asdict(metadata), **analysis},
                )
            else:
                self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "frame": asdict(metadata)})
        except OverflowError as exc:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": str(exc)})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except RuntimeError as exc:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": str(exc)},
            )
        except Exception as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": f"服务器处理失败：{exc}"},
            )


def guess_lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="独立的 Rokid 摄像头电脑显示测试服务")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9088)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), DemoHandler)
    lan_ip = guess_lan_ip()
    print()
    print("Rokid Camera Link Demo 已启动")
    print(f"电脑监看页： http://127.0.0.1:{args.port}/")
    print(f"采集端地址： http://{lan_ip}:{args.port}/capture.html")
    print(f"原始上传接口：http://{lan_ip}:{args.port}/api/frame")
    print("按 Ctrl+C 停止。")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止 Demo...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
