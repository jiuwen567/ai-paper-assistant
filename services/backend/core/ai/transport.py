import json
import os
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import suppress
from functools import lru_cache

from django.conf import settings

from core.common.errors import ParseFailure

RUN_SECONDS = 90


LINE_LIMIT = 100_000


OUTPUT_LIMIT = 1_000_000


@lru_cache(maxsize=1)
def node_executable():
    launcher = shutil.which("node")
    if not launcher:
        raise ParseFailure("runner_missing", "Pi 执行环境不可用，请检查部署。")
    try:
        # Volta 等启动器依赖用户 HOME；先解析真正的二进制，再隔离子进程环境。
        result = subprocess.run(
            [
                launcher,
                "-p",
                "JSON.stringify({path:process.execPath,major:Number(process.versions.node.split('.')[0])})",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        runtime = json.loads(result.stdout)
        if runtime["major"] < 24:
            raise ValueError("node_version")
        return runtime["path"]
    except (subprocess.SubprocessError, ValueError, KeyError) as error:
        raise ParseFailure("runner_missing", "Pi 执行需要 Node.js 24 或更高版本。") from error


def run_pi(config, handle, checkpoint, *, timeout_seconds=None):
    executable = node_executable()
    timeout_seconds = timeout_seconds or RUN_SECONDS
    if not settings.PI_RUNNER.is_file():
        raise ParseFailure("runner_missing", "Pi 执行环境不可用，请检查部署。")
    with tempfile.TemporaryDirectory(prefix="paper-pi-") as directory:
        process = subprocess.Popen(
            [executable, str(settings.PI_RUNNER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=directory,
            env={
                "PATH": os.path.dirname(executable),
                "HOME": directory,
                "LANG": "C.UTF-8",
                "NODE_ENV": "production",
            },
            start_new_session=True,
        )
        try:

            def send(value):
                process.stdin.write((json.dumps(value, ensure_ascii=False) + "\n").encode())
                process.stdin.flush()

            send(config)
            started, checked = time.monotonic(), 0
            buffer = b""
            total, expected = 0, 1
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    now = time.monotonic()
                    if now - started >= timeout_seconds:
                        raise ParseFailure(
                            "model_timeout", "模型任务超时，可重试。", retryable=True
                        )
                    if now - checked >= 1:
                        if not checkpoint():
                            return
                        checked = now
                    if not selector.select(timeout=min(0.5, timeout_seconds - (now - started))):
                        continue
                    block = os.read(process.stdout.fileno(), 16384)
                    if not block:
                        raise ParseFailure(
                            "runner_exited", "Pi 执行进程中断，可重试。", retryable=True
                        )
                    total += len(block)
                    buffer += block
                    if total > OUTPUT_LIMIT:
                        raise ParseFailure("runner_output_limit", "模型执行输出超过上限。")
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if len(line) > LINE_LIMIT:
                            raise ParseFailure("runner_output_limit", "模型执行输出超过上限。")
                        try:
                            message = json.loads(line)
                        except (ValueError, UnicodeError) as error:
                            raise ParseFailure("runner_protocol", "Pi 执行协议异常。") from error
                        if not isinstance(message, dict) or message.get("id") != expected:
                            raise ParseFailure("runner_protocol", "Pi 执行协议序号异常。")
                        expected += 1
                        result = handle(message)
                        if result is None:
                            return
                        send({"id": message["id"], "ok": True, "result": result})
                        if message["type"] == "done":
                            return
                    if len(buffer) > LINE_LIMIT:
                        raise ParseFailure("runner_output_limit", "模型执行输出超过上限。")
        finally:
            # 同一组内终止并回收；不能让迟到回包进入下一次重试。
            if process.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            with suppress(BrokenPipeError):
                process.stdin.close()
            process.stdout.close()
