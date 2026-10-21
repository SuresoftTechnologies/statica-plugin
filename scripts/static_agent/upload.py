from pathlib import Path

from . import analyzer, changes, languages, tu_history, workspace


def run_upload(project_dir, parallel=None):
    """워크스페이스 전체를 분석하고 서버에 업로드한다 (-w 스코프)."""
    project_dir = Path(project_dir)
    ws = workspace.find_workspace_for(project_dir)
    if ws is None:
        return {"ok": False, "command": "upload", "code": "NEEDS_BOOTSTRAP",
                "projectDir": str(project_dir),
                "message": "이 프로젝트에 연결된 STATIC 워크스페이스가 없습니다."}
    key = workspace.project_key(ws)
    if not key:
        return {"ok": False, "command": "upload", "code": "NO_PROJECT_KEY",
                "workspace": str(ws),
                "message": f"app.data.json 에 projectKey 가 없습니다: {ws}"}

    agent_json = workspace.read_agent_json(ws) or {}
    language_id = languages.of_agent_json(agent_json)
    if languages.is_plugin(language_id):
        # 일반 분석의 --no-upload 를 빼고, 변경이 없어도 전량 분석·업로드한다.
        from . import plugin_pipeline
        return plugin_pipeline.run_upload(project_dir, ws, agent_json,
                                        languages.get(language_id), key)

    # 분석을 **시작하기 전에** 찍는다. 끝난 시각을 쓰면 분석이 도는 동안 저장된
    # 편집이 영영 stale 로 잡히지 않는다 (tu_history.now 참조).
    started = tu_history.now()
    run = analyzer.analyze_workspace(ws, key, parallel=parallel)
    result = {"ok": run["ok"], "command": "upload", "workspace": str(ws),
              "projectKey": key, "returncode": run["returncode"]}
    if run["ok"]:
        # -w 스코프는 워크스페이스의 모든 TU 를 분석기에게 넘긴다. 그중 내용이 안
        # 바뀐 TU 는 분석기가 건너뛰고 아무 것도 쓰지 않으므로, 여기서 기록해 주지
        # 않으면 방금 전체 분석을 마쳤는데도 다음 Stop 훅이 그것들을 다시 분석
        # 대상으로 잡는다.
        #
        # 실패한 모듈은 통째로 뺀다. `-w` 는 실행 전체에 대해 종료 코드 하나만
        # 돌려주므로 어느 TU 가 실패했는지 여기서 알 수 없고, 실패한 것까지
        # "분석 완료"로 적으면 다음 실행이 재시도하지 못한다. 모듈 단위로 빼는
        # 것은 안전한 쪽으로 틀린 판단이다 — 성공한 TU 가 한 번 더 도는 것은
        # 손해지만, 실패한 TU 를 영영 건너뛰는 것은 고장이다.
        failed = set(analyzer.read_failures(ws))
        analyzed = {tu: started for tu in changes.tu_dirs(ws)
                    if tu.parent.parent.name not in failed}
        tu_history.record(ws, analyzed)
        result["failedModules"] = sorted(failed)
        result["message"] = f"전체 분석과 업로드를 마쳤습니다 · 프로젝트 {key}"
    else:
        result["code"] = "ANALYZE_FAILED"
        result["hint"] = run.get("hint")
        result["stderr"] = run.get("stderr", "")[-2000:]
        result["message"] = "전체 분석 또는 업로드에 실패했습니다."
    return result
