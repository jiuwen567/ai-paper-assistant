from worker.app import app


@app.task(name="system.ping")
def ping():
    """仅供工程联调，不创建业务任务或调用模型。"""
    return {"status": "ok", "service": "worker"}
