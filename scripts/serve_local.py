"""Loopback-only workbench sharing the enriched CLI's persistent runtime."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import socket
import sys
import tempfile
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_BODY_BYTES = 2 * MAX_FILE_BYTES + 65536


class RequestError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def parse_uploads(content_type: str, body: bytes) -> dict[str, bytes]:
    """Parse exactly two bounded CSV parts; client filenames never become paths."""
    if len(body) > MAX_BODY_BYTES:
        raise RequestError(413, "Общий размер файлов превышает 20 MiB.")
    if "\r" in content_type or "\n" in content_type:
        raise RequestError(400, "Некорректный тип загрузки.")
    try:
        message = BytesParser(policy=policy.default).parsebytes(
            ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode("ascii") + body)
    except (UnicodeError, ValueError) as error:
        raise RequestError(400, "Не удалось прочитать загруженные файлы.") from error
    if message.get_content_type() != "multipart/form-data" or not message.is_multipart() or message.defects:
        raise RequestError(400, "Нужны два CSV-файла в multipart/form-data.")
    parts = list(message.iter_parts())
    if len(parts) != 2:
        raise RequestError(400, "Выберите ровно два файла: закупки и ТРУ.")
    files = {}
    for part in parts:
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        if (part.is_multipart() or part.defects or part.get_content_disposition() != "form-data"
                or name not in ("notices", "items") or name in files
                or not filename or not filename.casefold().endswith(".csv")
                or part.get("Content-Transfer-Encoding") not in (None, "binary", "8bit")):
            raise RequestError(400, "Нужны отдельные CSV-файлы в полях notices и items.")
        data = part.get_payload(decode=True)
        if not data:
            raise RequestError(400, "Один из выбранных файлов пуст.")
        if len(data) > MAX_FILE_BYTES:
            raise RequestError(413, "Каждый CSV должен быть не больше 10 MiB.")
        files[name] = data
    return files


class RuntimeService:
    """One worker owns SQLite connections and accepts one inference at a time."""
    def __init__(self, runtime_factory=None):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rlt-runtime")
        self.busy = threading.Lock()
        self.runtime = None
        self.initialized = self.executor.submit(self._load_with_logging, runtime_factory)

    def _load_with_logging(self, factory):
        try:
            return self._initialize(factory)
        except Exception:
            logging.exception("Local runtime initialization failed")
            raise

    def _initialize(self, factory):
        sys.path.insert(0, str(ROOT / "src"))
        from rlt_lab.data import NOTICE_COLUMNS, ITEM_COLUMNS
        self.schemas = {"notices": NOTICE_COLUMNS, "items": ITEM_COLUMNS}
        if factory is None:
            sys.path.insert(0, str(ROOT / "scripts"))
            from recommend_enriched import EnrichedRuntime
            factory = EnrichedRuntime
        self.runtime = factory()
        return self.runtime.catalog.metadata()

    def info(self):
        state = {"ready": self.initialized.done() and self.initialized.exception() is None,
                 "busy": self.busy.locked(), "max_file_mib": 10, "max_files": 2,
                 "local_only": True, "team": "404: Loss not found"}
        if self.initialized.done():
            if self.initialized.exception() is not None:
                state["error"] = "Не удалось загрузить локальную модель. Проверьте журнал сервера."
            else:
                state["external_catalog"] = self.initialized.result()
                state["schemas"] = self.schemas
        return state

    def recommend(self, files):
        if not self.info()["ready"]:
            raise RequestError(503, "Модель ещё загружается или недоступна. Повторите после готовности сервера.")
        if not self.busy.acquire(blocking=False):
            raise RequestError(409, "Уже выполняется другая подборка. Дождитесь её завершения.")
        try:
            with tempfile.TemporaryDirectory(prefix="rlt-web-") as temporary:
                paths = {key: Path(temporary) / (key + ".csv") for key in ("notices", "items")}
                for key, path in paths.items():
                    path.write_bytes(files[key])
                try:
                    return self.executor.submit(self.runtime.recommend, paths["notices"], paths["items"], top_k=10).result()
                except ValueError as error:
                    # Input errors remain actionable; omit generated paths from the API.
                    detail = str(error).replace(str(temporary) + "/notices.csv", "Закупки CSV").replace(str(temporary) + "/items.csv", "ТРУ CSV")
                    raise RequestError(422, "Проверьте данные CSV. " + detail[:900]) from error
        finally:
            self.busy.release()

    def close(self):
        try:
            error = self.initialized.exception()
            if error is None and self.runtime is not None:
                self.executor.submit(self.runtime.close).result()
        finally:
            self.executor.shutdown(wait=True)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port=8901, service=None):
        self.service = service or RuntimeService()
        super().__init__(("127.0.0.1", port), Handler)
        self.allowed_hosts = {"127.0.0.1:" + str(self.server_port), "localhost:" + str(self.server_port)}


class Handler(BaseHTTPRequestHandler):
    server_version = "RLTLocal/1"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def _check_origin(self, *, write=False):
        if self.headers.get_all("Host", []) != [self.headers.get("Host")] or self.headers.get("Host") not in self.server.allowed_hosts:
            raise RequestError(403, "Доступ разрешён только через локальный адрес сервера.")
        origin = self.headers.get("Origin")
        allowed = {"http://" + host for host in self.server.allowed_hosts}
        if len(self.headers.get_all("Origin", [])) > 1 or (write and origin is None) or (origin is not None and origin not in allowed):
            raise RequestError(403, "Запрос должен приходить с локальной страницы подбора.")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise RequestError(403, "Межсайтовый запрос отклонён.")

    def _send(self, status, data, content_type="application/json; charset=utf-8"):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            self._check_origin()
            path = urlsplit(self.path).path
            if path in ("/health", "/info"):
                self._send(200, self.server.service.info())
                return
            static = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path not in static:
                raise RequestError(404, "Страница не найдена.")
            filename, content_type = static[path]
            self._send(200, (WEB / filename).read_bytes(), content_type)
        except RequestError as error:
            self._send(error.status, {"error": error.message})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        try:
            self._check_origin(write=True)
            if urlsplit(self.path).path != "/recommend":
                raise RequestError(404, "Метод не найден.")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isdigit() or self.headers.get("Transfer-Encoding"):
                raise RequestError(400, "Требуется один корректный Content-Length.")
            size = int(lengths[0])
            if not 0 < size <= MAX_BODY_BYTES:
                raise RequestError(413, "Загрузите два CSV размером до 10 MiB каждый.")
            body = self.rfile.read(size)
            if len(body) != size:
                raise RequestError(400, "Загрузка файлов прервалась. Повторите запрос.")
            files = parse_uploads(self.headers.get("Content-Type", ""), body)
            self._send(200, self.server.service.recommend(files))
        except RequestError as error:
            self._send(error.status, {"error": error.message})
        except (socket.timeout, TimeoutError):
            self._send(408, {"error": "Не удалось полностью загрузить файлы за отведённое время."})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            logging.exception("Local recommendation failed")
            self._send(500, {"error": "Подборка не завершилась. Исходные файлы не изменены. Проверьте журнал сервера и повторите запрос."})


def main():
    parser = argparse.ArgumentParser(description="Локальный веб-стенд RLT")
    parser.add_argument("--port", type=int, default=8901)
    args = parser.parse_args()
    server = LocalServer(args.port)
    print(f"RLT: http://127.0.0.1:{server.server_port} (модель загружается один раз)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.service.close()


if __name__ == "__main__":
    main()
