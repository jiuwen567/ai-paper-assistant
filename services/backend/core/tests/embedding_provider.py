"""受控嵌入 HTTP 夹具：固定向量，不运行模型，也不代表语义检索质量。"""

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from django.test import override_settings


def response_for(payload):
    dimension = payload.get("dimensions", 512)
    vectors = []
    for index, text in enumerate(payload["input"]):
        # 仅给自制温度/光照案例不同坐标，验证排序与来源回查。
        vector = [1.0, 0.0] if "光照" not in text else [0.0, 1.0]
        vectors.append({"index": index, "embedding": (vector + [0.0] * dimension)[:dimension]})
    return {"data": vectors}


def handler_for(respond, requests):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(
                {
                    "path": self.path,
                    "payload": payload,
                    "authorization": self.headers.get("Authorization"),
                }
            )
            status, body, headers = respond(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())

    return Handler


@contextmanager
def provider(respond=None):
    requests = []
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        handler_for(respond or (lambda payload: (200, response_for(payload), {})), requests),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with override_settings(
            DEBUG=True,
            EMBEDDING_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
            EMBEDDING_API_KEY="synthetic-embedding-key",
            EMBEDDING_MODEL="fixture-embedding",
            EMBEDDING_DIMENSION=512,
            EMBEDDING_SEND_DIMENSIONS=True,
            EMBEDDING_MODEL_REVISION="fixture-v1",
        ):
            yield requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    # 仅用于显式启动的 Compose 浏览器验收覆盖配置。
    server = ThreadingHTTPServer(
        ("0.0.0.0", 8766), handler_for(lambda payload: (200, response_for(payload), {}), [])
    )
    server.serve_forever()
