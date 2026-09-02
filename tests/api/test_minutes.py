from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from meeting_api.config import Settings
from meeting_api.minutes import prompt as minutes_prompt
from meeting_api.minutes.adapter import (
    AutoMinutesAdapter,
    ClaudeCliAdapter,
    CodexCliAdapter,
    FakeMinutesAdapter,
    MinutesCliError,
    resolve_minutes_adapter,
)
from meeting_api.minutes.prompt import build_minutes_prompt, load_minutes_glossary
from meeting_api.models import HotwordEntry, Meeting
from meeting_api.worker import Worker

NOTE = "纪要文本会发送到 Claude/OpenAI 云端，音频不会上传"


def _prepare_generating_minutes(client, *, keep_unknown: bool = False) -> str:
    # 不填标题：创建时填了标题就视为用户命名，纪要不再自动改名。
    created = client.post(
        "/api/meetings",
        json={"expected_speakers": 2},
    )
    assert created.status_code == 201
    meeting_id = created.json()["id"]

    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert uploaded.status_code == 200
    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == (
        "AWAITING_SPEAKER_REVIEW"
    )

    second_decision = (
        {"cluster_id": "S2", "kind": "KEEP_UNKNOWN"}
        if keep_unknown
        else {
            "cluster_id": "S2",
            "kind": "NEW_PERSON",
            "display_name": "李雷",
        }
    )
    reviewed = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {
                    "cluster_id": "S1",
                    "kind": "NEW_PERSON",
                    "display_name": "王芳",
                },
                second_decision,
            ]
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["state"] == "GENERATING_MINUTES"
    return meeting_id


def test_fake_adapter_success_makes_meeting_ready_and_exposes_minutes(client):
    meeting_id = _prepare_generating_minutes(client)

    assert client.app.state.worker.process_next() == meeting_id

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.json()["state"] == "READY"
    response = client.get(f"/api/meetings/{meeting_id}/minutes")
    assert response.status_code == 200
    assert response.json()["markdown"].startswith("# 会议纪要")
    assert response.json()["note"] == NOTE

    transcript_path = (
        client.app.state.settings.data_dir
        / "meetings"
        / meeting_id
        / "transcript.txt"
    )
    assert transcript_path.is_file()
    transcript = transcript_path.read_text(encoding="utf-8")
    assert "王芳 00:00-00:05\n这是 meeting.wav 的假转写第一段" in transcript
    assert "李雷 00:05-00:10\n这是假转写第二段" in transcript
    assert "[0.00" not in transcript
    assert str(client.app.state.settings.data_dir) not in response.text


def test_unconfirmed_speakers_add_warning_at_start_of_minutes(client):
    meeting_id = _prepare_generating_minutes(client, keep_unknown=True)

    assert client.app.state.worker.process_next() == meeting_id

    response = client.get(f"/api/meetings/{meeting_id}/minutes")
    assert response.status_code == 200
    assert response.json()["markdown"].startswith("含未确认说话人")


def test_cli_error_makes_partial_ready_then_retry_can_succeed(client):
    meeting_id = _prepare_generating_minutes(client)
    client.app.state.worker.minutes_adapter = FakeMinutesAdapter(
        error=MinutesCliError("模拟配额不足")
    )

    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "PARTIAL_READY"

    retried = client.post(f"/api/meetings/{meeting_id}/minutes/retry")
    assert retried.status_code == 200
    assert retried.json()["state"] == "GENERATING_MINUTES"

    client.app.state.worker.minutes_adapter = FakeMinutesAdapter()
    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "READY"
    assert client.get(f"/api/meetings/{meeting_id}/minutes").status_code == 200


class RecordingAdapter:
    """记录 worker 实际交给纪要 CLI 的提示词。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, transcript: str) -> str:
        self.prompts.append(transcript)
        return "# 会议纪要\n\n- 已生成"


class MarkdownAdapter:
    def __init__(self, markdown: str) -> None:
        self.markdown = markdown

    def generate(self, transcript: str) -> str:
        del transcript
        return self.markdown


def test_minutes_prompt_instructions_match_authoritative_data_file():
    # data/ 整目录 gitignore；本机 Mini 可放权威模板与常量逐字同步。
    # CI checkout 无此文件。缺文件时跳过，避免把本机同步检查当成仓库必有资产。
    prompt_path = Path(__file__).resolve().parents[2] / "data" / "minutes_prompt.md"
    if not prompt_path.is_file():
        pytest.skip("data/minutes_prompt.md 是本机权威模板，不入 git")
    expected = prompt_path.read_text(encoding="utf-8")
    assert minutes_prompt.MINUTES_PROMPT_INSTRUCTIONS == expected


def test_minutes_prompt_uses_public_anonymous_speaker_example():
    assert "说话人 2" in minutes_prompt.MINUTES_PROMPT_INSTRUCTIONS
    assert "未知说话人（S2）" not in minutes_prompt.MINUTES_PROMPT_INSTRUCTIONS


def test_worker_wraps_transcript_with_minutes_instructions(client):
    # 裸逐字稿会让 CLI 自由发挥（解释、评论环境）；必须带明确任务指令。
    meeting_id = _prepare_generating_minutes(client)
    adapter = RecordingAdapter()
    client.app.state.worker.minutes_adapter = adapter

    assert client.app.state.worker.process_next() == meeting_id

    (prompt,) = adapter.prompts
    assert "会议纪要" in prompt
    assert "只输出纪要正文" in prompt
    assert "议程时间轴" in prompt
    assert "3～6 条要点" in prompt
    assert "待决问题与风险" in prompt
    assert "5～8 个" in prompt
    assert "以会议最终认定的口径" in prompt
    assert "换算成绝对日期" in prompt
    assert "不要泛化成「某资源」" in prompt
    assert "不堆砌直接引语" in prompt
    assert "近音错词" in prompt
    assert "后续跟进" in prompt
    assert "@待认领" in prompt
    assert "不得编造" in prompt
    assert "假转写第一段" in prompt  # 逐字稿本体在指令之后
    assert "王芳 00:00-00:05\n这是 meeting.wav 的假转写第一段" in prompt
    assert "[0.00" not in prompt
    assert prompt.index("只输出纪要正文") < prompt.index("假转写第一段")

    # 磁盘上的 transcript.txt 仍是纯逐字稿，不掺指令。
    transcript_path = (
        client.app.state.settings.data_dir / "meetings" / meeting_id / "transcript.txt"
    )
    text = transcript_path.read_text(encoding="utf-8")
    assert "王芳 00:00-00:05\n这是 meeting.wav 的假转写第一段" in text
    assert "[0.00" not in text
    assert "只输出纪要正文" not in text


def test_worker_prompt_uses_review_order_label_for_unknown_speaker(client):
    meeting_id = _prepare_generating_minutes(client, keep_unknown=True)
    adapter = RecordingAdapter()
    client.app.state.worker.minutes_adapter = adapter

    assert client.app.state.worker.process_next() == meeting_id

    (prompt,) = adapter.prompts
    assert "说话人 2 00:05-00:10\n这是假转写第二段" in prompt
    assert "未知说话人" not in prompt
    assert "S2" not in prompt


def test_build_minutes_prompt_inserts_glossary_before_transcript_without_nearest_note():
    prompt = build_minutes_prompt(
        "王芳 00:00-00:05\n剑山项目进展",
        glossary="- 见山：教育项目品牌\n\n",
    )

    glossary_block = (
        "公司术语表（逐字稿为语音识别产物，其中的近音误写请按下表纠正为标准写法；"
        "注解仅供理解，不要照抄进纪要）：\n- 见山：教育项目品牌\n"
    )
    assert glossary_block in prompt
    assert "就近归属" not in prompt
    assert "（待核）" not in prompt
    assert prompt.index("公司术语表") < prompt.index("\n会议逐字稿：\n")


def test_build_minutes_prompt_inserts_meeting_date_anchor_before_glossary():
    prompt = build_minutes_prompt(
        "王芳 00:00-00:05\n明天继续看报价",
        glossary="- 见山：教育项目品牌\n",
        meeting_date=date(2026, 8, 31),
    )

    assert (
        "会议日期：2026-08-31（周一）。标题日期与「明天」「下周二」等相对时间换算以此为锚点。"
        "若该日期与逐字稿内容明显矛盾，以逐字稿为准。"
    ) in prompt
    assert "明天" in prompt
    assert (
        prompt.index("说话人身份未确认时")
        < prompt.index("会议日期：2026-08-31（周一）")
        < prompt.index("公司术语表（逐字稿为语音识别产物")
        < prompt.index("\n会议逐字稿：\n")
    )

    prompt_without_date = build_minutes_prompt("王芳 00:00-00:05\n明天继续看报价")
    assert "会议日期：" not in prompt_without_date


def test_build_minutes_prompt_without_glossary_keeps_legacy_bytes():
    transcript = "王芳 00:00-00:05\n普通逐字稿"

    legacy_prompt = build_minutes_prompt(transcript)
    prompt_with_none = build_minutes_prompt(transcript, glossary=None)

    assert prompt_with_none == legacy_prompt
    # 指令头里可以提到「公司术语表（如有）」；这里断言的是术语表块本身不存在。
    assert "公司术语表（逐字稿为语音识别产物" not in prompt_with_none
    assert "会议日期：" not in prompt_with_none


def test_meeting_date_from_created_at_treats_naive_datetime_as_utc():
    meeting_date = minutes_prompt.meeting_date_from_created_at(
        datetime(2026, 8, 30, 20, 0),
        target_tz=ZoneInfo("Asia/Shanghai"),
    )

    assert meeting_date == date(2026, 8, 31)


def test_load_minutes_glossary_matches_template_empty_file_behavior(tmp_path):
    assert load_minutes_glossary(tmp_path) is None

    glossary_path = tmp_path / "minutes_glossary.md"
    glossary_path.write_text("   \n", encoding="utf-8")

    assert load_minutes_glossary(tmp_path) is None


def test_worker_passes_hotword_notes_and_minutes_glossary_to_prompt_without_polluting_transcript(
    client,
):
    meeting_id = _prepare_generating_minutes(client)
    with client.app.state.session_factory() as session:
        session.add(HotwordEntry(word="裸词"))
        session.add(HotwordEntry(word="见山", note="教育项目品牌"))
        session.commit()
    hotword_note_line = "- 见山：教育项目品牌"
    bare_hotword_line = "- 裸词"
    glossary_line = "- 见山：教育项目品牌"
    (client.app.state.settings.data_dir / "minutes_glossary.md").write_text(
        f"{glossary_line}\n- 文件补充内容\n", encoding="utf-8"
    )
    adapter = RecordingAdapter()
    client.app.state.worker.minutes_adapter = adapter

    assert client.app.state.worker.process_next() == meeting_id

    (prompt,) = adapter.prompts
    assert hotword_note_line in prompt
    assert bare_hotword_line in prompt
    assert glossary_line in prompt
    assert "- 文件补充内容" in prompt
    assert prompt.index(hotword_note_line) < prompt.index("- 文件补充内容")
    assert prompt.index("- 文件补充内容") < prompt.index("会议逐字稿：")

    transcript_path = (
        client.app.state.settings.data_dir / "meetings" / meeting_id / "transcript.txt"
    )
    transcript = transcript_path.read_text(encoding="utf-8")
    assert hotword_note_line not in transcript
    assert "- 文件补充内容" not in transcript


def test_worker_passes_meeting_date_anchor_to_prompt_without_polluting_transcript(client):
    meeting_id = _prepare_generating_minutes(client)
    adapter = RecordingAdapter()
    client.app.state.worker.minutes_adapter = adapter

    assert client.app.state.worker.process_next() == meeting_id

    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        expected_date = minutes_prompt.meeting_date_from_created_at(meeting.created_at)

    (prompt,) = adapter.prompts
    expected_line_prefix = f"会议日期：{expected_date.isoformat()}"
    assert expected_line_prefix in prompt
    assert prompt.index(expected_line_prefix) < prompt.index("\n会议逐字稿：\n")

    transcript_path = (
        client.app.state.settings.data_dir / "meetings" / meeting_id / "transcript.txt"
    )
    transcript = transcript_path.read_text(encoding="utf-8")
    assert "会议日期：" not in transcript


def test_minutes_generation_updates_title_from_h1_with_cleaned_date_prefix(client):
    meeting_id = _prepare_generating_minutes(client)
    adapter = MarkdownAdapter(
        "# 2026-08-31：26-08-31：见山社团落地与升学辅导试点\n\n正文"
    )
    client.app.state.worker.minutes_adapter = adapter

    assert client.app.state.worker.process_next() == meeting_id

    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        expected_date = minutes_prompt.meeting_date_from_created_at(
            meeting.created_at
        ).strftime("%y-%m-%d")
        assert meeting.title == f"{expected_date}：见山社团落地与升学辅导试点"


def test_minutes_generation_keeps_user_edited_title_when_markdown_has_h1(client):
    meeting_id = _prepare_generating_minutes(client)
    client.patch(f"/api/meetings/{meeting_id}", json={"title": "人工标题"})
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        assert meeting.title_user_edited is True
    adapter = MarkdownAdapter("# 模型生成标题\n\n正文")
    client.app.state.worker.minutes_adapter = adapter

    assert client.app.state.worker.process_next() == meeting_id

    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        assert meeting.title == "人工标题"


def test_minutes_retry_keeps_user_edited_title_locked(client):
    meeting_id = _prepare_generating_minutes(client)
    client.patch(f"/api/meetings/{meeting_id}", json={"title": "重试也保留的标题"})
    client.app.state.worker.minutes_adapter = FakeMinutesAdapter(
        error=MinutesCliError("模拟首次生成失败")
    )

    assert client.app.state.worker.process_next() == meeting_id
    assert client.post(f"/api/meetings/{meeting_id}/minutes/retry").status_code == 200

    client.app.state.worker.minutes_adapter = MarkdownAdapter("# 重试生成的新标题\n\n正文")
    assert client.app.state.worker.process_next() == meeting_id

    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        assert meeting.title == "重试也保留的标题"


def test_minutes_generation_truncates_auto_title_to_200_chars(client):
    meeting_id = _prepare_generating_minutes(client)
    adapter = MarkdownAdapter(f"# 08-31 会议：{'长' * 260}\n\n正文")
    client.app.state.worker.minutes_adapter = adapter

    assert client.app.state.worker.process_next() == meeting_id

    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        assert len(meeting.title) == 200
        assert meeting.title.startswith("26-")


def test_worker_omits_glossary_block_when_hotwords_and_file_are_empty(client):
    meeting_id = _prepare_generating_minutes(client)
    adapter = RecordingAdapter()
    client.app.state.worker.minutes_adapter = adapter

    assert client.app.state.worker.process_next() == meeting_id

    (prompt,) = adapter.prompts
    assert "公司术语表（逐字稿为语音识别产物" not in prompt


def test_custom_minutes_template_overrides_default_instructions(client):
    # data/minutes_prompt.md 存在即覆盖默认指令头；逐字稿仍附在其后，
    # 用户可以不改代码调纪要风格。
    meeting_id = _prepare_generating_minutes(client)
    (client.app.state.settings.data_dir / "minutes_prompt.md").write_text(
        "请用一句话总结本次会议。", encoding="utf-8"
    )
    adapter = RecordingAdapter()
    client.app.state.worker.minutes_adapter = adapter

    assert client.app.state.worker.process_next() == meeting_id

    (prompt,) = adapter.prompts
    assert prompt.startswith("请用一句话总结本次会议。")
    assert "只输出纪要正文" not in prompt
    assert "假转写第一段" in prompt


def test_blank_minutes_template_falls_back_to_default(client):
    meeting_id = _prepare_generating_minutes(client)
    (client.app.state.settings.data_dir / "minutes_prompt.md").write_text(
        "   \n", encoding="utf-8"
    )
    adapter = RecordingAdapter()
    client.app.state.worker.minutes_adapter = adapter

    assert client.app.state.worker.process_next() == meeting_id

    (prompt,) = adapter.prompts
    assert "议程时间轴" in prompt
    assert "每人只列一次" in prompt
    assert "更不要把几套条款挤进同一条要点" in prompt
    assert "待决问题与风险" in prompt
    assert "5～8 个" in prompt
    assert "以会议最终认定的口径" in prompt
    assert "换算成绝对日期" in prompt
    assert "不要泛化成「某资源」" in prompt


def test_auto_adapter_falls_back_to_codex_when_claude_fails(tmp_path):
    # 真机场景：claude 在 PATH 但未登录（或配额不足）时不该整场卡住，
    # 本机若有 codex 就换通道再试一次。
    both = tmp_path / "both"
    both.mkdir()
    _write_script(both / "claude", "echo 'Not logged in' >&2\nexit 1")
    _write_script(both / "codex", "cat")

    adapter = AutoMinutesAdapter(path=str(both))

    assert adapter.generate("逐字稿正文") == "逐字稿正文"


def test_auto_adapter_reports_both_errors_when_all_clis_fail(tmp_path):
    both = tmp_path / "both"
    both.mkdir()
    _write_script(both / "claude", "echo 'Not logged in' >&2\nexit 1")
    _write_script(both / "codex", "echo '配额不足' >&2\nexit 2")

    adapter = AutoMinutesAdapter(path=str(both))

    with pytest.raises(MinutesCliError) as excinfo:
        adapter.generate("逐字稿正文")
    message = str(excinfo.value)
    assert "claude" in message
    assert "codex" in message
    assert "Not logged in" in message
    assert "配额不足" in message


def test_claude_command_uses_print_json_and_disables_file_tools():
    command = ClaudeCliAdapter().build_command()

    assert command[:2] == ["claude", "-p"]
    assert command[command.index("--output-format") + 1] == "json"
    disabled = command[command.index("--disallowedTools") + 1]
    assert {"Read", "Write", "Edit", "Glob", "Grep", "Bash"} <= set(
        disabled.split(",")
    )
    assert "--bare" not in command


def test_codex_command_uses_exec_without_bare():
    command = CodexCliAdapter().build_command()

    assert command[:2] == ["codex", "exec"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    # 提示词经 stdin（"-"）传入，不进 argv。
    assert command[-1] == "-"
    assert "--bare" not in command


def _write_script(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_claude_adapter_sends_transcript_via_stdin_not_argv(tmp_path):
    # 逐字稿走 stdin，避免长会议撞 argv 单参数上限（ARG_MAX）。
    fake_claude = _write_script(
        tmp_path / "claude",
        'input=$(cat)\nprintf \'{"result": "收到:%s"}\' "$input"',
    )

    adapter = ClaudeCliAdapter(executable=str(fake_claude))

    assert "逐字稿正文" not in adapter.build_command()
    assert adapter.generate("逐字稿正文") == "收到:逐字稿正文"


def test_codex_adapter_sends_transcript_via_stdin_not_argv(tmp_path):
    fake_codex = _write_script(tmp_path / "codex", "cat")

    adapter = CodexCliAdapter(executable=str(fake_codex))

    assert "逐字稿正文" not in adapter.build_command()
    assert adapter.generate("逐字稿正文") == "逐字稿正文"


def test_nonzero_exit_and_timeout_raise_minutes_cli_error(tmp_path):
    failing = _write_script(tmp_path / "claude", "echo '配额不足' >&2\nexit 3")
    hanging = _write_script(tmp_path / "codex", "exec sleep 30")

    with pytest.raises(MinutesCliError, match="配额不足"):
        ClaudeCliAdapter(executable=str(failing)).generate("逐字稿正文")
    with pytest.raises(MinutesCliError, match="超时"):
        CodexCliAdapter(executable=str(hanging), timeout_seconds=0.2).generate("逐字稿正文")


def test_auto_adapter_prefers_claude_then_codex_then_fails(tmp_path):
    both = tmp_path / "both"
    both.mkdir()
    _write_script(both / "claude", "")
    _write_script(both / "codex", "")
    codex_only = tmp_path / "codex-only"
    codex_only.mkdir()
    _write_script(codex_only / "codex", "")
    empty = tmp_path / "empty"
    empty.mkdir()

    assert isinstance(AutoMinutesAdapter(path=str(both)).resolve(), ClaudeCliAdapter)
    assert isinstance(AutoMinutesAdapter(path=str(codex_only)).resolve(), CodexCliAdapter)
    with pytest.raises(MinutesCliError, match="未找到"):
        AutoMinutesAdapter(path=str(empty)).resolve()


def test_worker_default_adapter_follows_settings_backend(tmp_path):
    def make_worker(backend: str) -> Worker:
        return Worker(
            session_factory=None,
            settings=Settings(data_dir=tmp_path, minutes_backend=backend),
        )

    # 真实运行默认 auto：按本机 CLI 选择，绝不默默产出 fake 纪要。
    assert isinstance(make_worker("auto").minutes_adapter, AutoMinutesAdapter)
    assert isinstance(make_worker("fake").minutes_adapter, FakeMinutesAdapter)
    assert isinstance(resolve_minutes_adapter("claude"), ClaudeCliAdapter)
    assert isinstance(resolve_minutes_adapter("codex"), CodexCliAdapter)


def test_auto_without_any_cli_makes_meeting_partial_ready(client, tmp_path):
    meeting_id = _prepare_generating_minutes(client)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    client.app.state.worker.minutes_adapter = AutoMinutesAdapter(path=str(empty))

    assert client.app.state.worker.process_next() == meeting_id

    detail = client.get(f"/api/meetings/{meeting_id}").json()
    assert detail["state"] == "PARTIAL_READY"


def test_minutes_cli_settings_probes_executables_on_path(client, tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text("#!/bin/sh\n", encoding="utf-8")
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))

    response = client.get("/api/settings/minutes-cli")

    assert response.status_code == 200
    assert response.json() == {
        "claude_available": True,
        "codex_available": False,
        "note": NOTE,
    }
    assert not any(Path(fake_bin).as_posix() in str(value) for value in response.json().values())


def test_claude_command_disables_all_tools_mcp_and_session_persistence():
    # 逐字稿是不可信输入：会上一句「忽略上面的指令」不能变成一次工具调用。
    command = ClaudeCliAdapter().build_command()

    assert command[command.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in command
    assert "--no-session-persistence" in command
    assert "--bare" not in command


def test_codex_command_is_ephemeral_and_skips_git_repo_check():
    command = CodexCliAdapter().build_command()

    assert "--ephemeral" in command
    assert "--skip-git-repo-check" in command
    assert command[-1] == "-"


def test_cli_runs_in_empty_scratch_directory_not_repo_root(tmp_path):
    # 子进程若继承仓库根目录，claude 会读进 CLAUDE.md/.claude 设置，codex 会把
    # AGENTS.md 当指令；必须在空的临时目录里跑，且跑完即清理。
    fake_codex = _write_script(
        tmp_path / "codex",
        'printf "%s|%s" "$PWD" "$(ls -A | wc -l | tr -d \' \')"',
    )

    output = CodexCliAdapter(executable=str(fake_codex)).generate("逐字稿正文")

    cwd, entries = output.split("|")
    assert Path(cwd).resolve() != Path.cwd().resolve()
    assert entries == "0"
    assert not Path(cwd).exists()


def test_worker_gives_minutes_and_cleaning_separate_configurable_timeouts(tmp_path):
    # 整份纪要要吞四万字再吐六千字，和 3000 字一批的清洗不能共用 120 秒。
    settings = Settings(
        data_dir=tmp_path,
        minutes_backend="claude",
        minutes_timeout_seconds=900,
        cleaning_timeout_seconds=45,
    )

    worker = Worker(session_factory=None, settings=settings)

    assert isinstance(worker.minutes_adapter, ClaudeCliAdapter)
    assert worker.minutes_adapter.timeout_seconds == 900
    assert isinstance(worker.cleaner_adapter, ClaudeCliAdapter)
    assert worker.cleaner_adapter.timeout_seconds == 45


def test_auto_adapter_passes_timeout_to_resolved_cli(tmp_path):
    both = tmp_path / "both"
    both.mkdir()
    _write_script(both / "claude", "")
    hanging = _write_script(tmp_path / "hang", "exec sleep 30")
    codex_only = tmp_path / "codex-only"
    codex_only.mkdir()
    (codex_only / "codex").symlink_to(hanging)

    resolved = AutoMinutesAdapter(path=str(both), timeout_seconds=7).resolve()
    assert resolved.timeout_seconds == 7

    with pytest.raises(MinutesCliError, match="超时"):
        AutoMinutesAdapter(path=str(codex_only), timeout_seconds=0.2).generate("逐字稿")


def test_default_timeouts_favor_long_minutes_generation():
    settings = Settings()

    assert settings.minutes_timeout_seconds >= 600
    assert settings.cleaning_timeout_seconds >= 120
