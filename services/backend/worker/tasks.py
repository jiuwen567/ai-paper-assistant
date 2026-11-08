from worker.app import app


@app.task(name="system.ping")
def ping():
    """仅供工程联调，不创建业务任务或调用模型。"""
    return {"status": "ok", "service": "worker"}


@app.task(name="jobs.execute", acks_late=True, reject_on_worker_lost=True, time_limit=300)
def execute_job(job_id):
    import time

    from core.common.errors import ParseFailure
    from core.jobs.service import claim, fail, heartbeat, publish
    from core.models import Job

    try:
        job = claim(job_id)
    except Job.DoesNotExist:
        return
    if job is None:
        return
    try:
        if job.kind == "ai":
            from core.ai.execution import execute_ai

            execute_ai(job)
            return
        if job.kind == "index":
            from core.search.jobs import execute_index

            execute_index(job)
            return
        if job.kind == "export":
            from core.exports.jobs import execute_export

            execute_export(job)
            return
        if job.kind == "parse":
            from core.materials.parse_jobs import execute_parse

            execute_parse(job)
            return
        if job.kind != "sample":
            fail(job.pk, job.generation, code="unknown_kind")
            return
        steps = job.input_snapshot["steps"]
        for step in range(steps):
            # 样例只计算字数；每个步骤（将来包括模型调用）之前重新检查授权与租约。
            if not heartbeat(job.pk, job.generation, int(step * 100 / steps)):
                return
            time.sleep(0.2)
        publish(
            job.pk,
            job.generation,
            {
                "characters": len(job.input_snapshot["text"]),
                "source_version": job.input_snapshot["source_version"],
            },
        )
    except Job.DoesNotExist:
        return  # 已删除任务的迟到 Worker 不再发布或重建数据。
    except ParseFailure as error:
        fail(
            job.pk,
            job.generation,
            code=error.code,
            message=error.message,
            retryable=error.retryable,
        )
    except Exception as error:
        # 只记录异常类型，不记录可能含密钥或材料的异常正文。
        fail(
            job.pk,
            job.generation,
            retryable=not isinstance(error, (KeyError, TypeError, ValueError)),
            code=f"execution_{type(error).__name__}"[:64],
        )


@app.task(name="jobs.recover")
def recover_jobs():
    from core.jobs.service import recover_jobs as recover

    return recover()


@app.task(name="graph.sync", acks_late=True, reject_on_worker_lost=True, time_limit=180)
def sync_graph_events():
    from core.graph.service import recover_events

    return recover_events()


@app.task(name="cleanup.execute", acks_late=True, reject_on_worker_lost=True, time_limit=300)
def execute_cleanup(request_id):
    from core.cleanup.service import execute

    execute(request_id)


@app.task(name="cleanup.recover")
def recover_cleanup():
    from core.cleanup.service import recover

    recover()
