from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator


class MeetingCreate(BaseModel):
    # 选填：留空或空白 = 未命名，上传后取文件名、纪要后自动命名；填了就是用户命名。
    title: str | None = Field(default=None, max_length=200)
    # 会议发生日；不填则按音频文件名或创建日推断。
    meeting_date: date | None = None
    expected_speakers: int | None = Field(default=None, ge=1)
    # 会议语言：英文会议转写与清洗输出英文原文，纪要仍用中文撰写。
    language: Literal["zh", "en"] = "zh"
    # 所属项目；不给或给 null 都表示「无项目」。
    project_id: str | None = None
    hotwords: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def blank_title_as_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("hotwords")
    @classmethod
    def hotwords_clean(cls, value: list[str]) -> list[str]:
        # 去首尾空白、去空项、去重且保序；空列表合法
        cleaned: list[str] = []
        for word in value:
            stripped = word.strip()
            if stripped and stripped not in cleaned:
                cleaned.append(stripped)
        return cleaned


class MeetingUpdate(BaseModel):
    """PATCH 只改给出的字段：标题、会议日期、语言、项目各自可选，但至少要给一个。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    meeting_date: date | None = None
    # 改语言不触发任何状态迁移，仅在下一次转写/重转写时生效。
    language: Literal["zh", "en"] | None = None
    # 「没给」= 保持原样；「给了 null」= 改成无项目。用 model_fields_set 区分。
    project_id: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("标题不能为空")
        return stripped

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if not self.model_fields_set & {
            "title",
            "meeting_date",
            "language",
            "project_id",
        }:
            raise ValueError("至少提供 title、meeting_date、language 或 project_id 之一")
        return self


class MeetingResponse(BaseModel):
    id: str
    title: str
    state: str
    expected_speakers: int | None
    language: Literal["zh", "en"]
    # 所属项目；未挂项目时两者都是 null。
    project_id: str | None
    project_name: str | None
    hotwords: list[str]
    created_at: datetime
    # 生效的会议日期与来源：user=用户填写 / filename=音频文件名 / created=创建日。
    meeting_date: date
    meeting_date_source: Literal["user", "filename", "created"]
    speakers: list[str]
    unknown_speaker_count: int
    # 来源 Plaud 云端录音时的 file_id；本地上传的会议为 null。
    plaud_file_id: str | None = None
    # FAILED / PARTIAL_READY 的失败原因，给人看的一句话；不含服务器路径。
    processing_error: str | None = None


class MeetingListResponse(BaseModel):
    items: list[MeetingResponse]


class UploadResponse(BaseModel):
    size: int
    sha256: str


class ProgressResponse(BaseModel):
    state: str
    processing_step: str | None
    # 步骤内进度，如清洗「3/12」；没有就是 None。
    detail: str | None = None
    seq: int


class PlaudImportRequest(MeetingCreate):
    """从 Plaud 导入：会议字段与新建会议一致，另带要导入的录音 id。"""

    plaud_file_id: str = Field(min_length=1, max_length=64)

    @field_validator("plaud_file_id")
    @classmethod
    def file_id_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("plaud_file_id 不能为空")
        return stripped


class PlaudUserResponse(BaseModel):
    nickname: str | None
    email: str | None


class PlaudStatusResponse(BaseModel):
    # Plaud 的任何问题都在这里以文案呈现，不抛 4xx/5xx。
    available: bool
    logged_in: bool
    user: PlaudUserResponse | None = None
    message: str | None = None


class PlaudLoginResponse(BaseModel):
    logged_in: bool
    message: str


class PlaudRecordingResponse(BaseModel):
    file_id: str
    name: str
    started_at: datetime
    duration_ms: int
    # 已导入过的录音回填对应会议 id，前端据此禁选并给「打开」入口。
    imported_meeting_id: str | None = None

    @field_serializer("started_at")
    def serialize_started_at(self, value: datetime) -> str:
        # 固定输出 "+00:00" 偏移（而不是 pydantic 默认的 "Z"），与前后端契约一致。
        return value.isoformat()


class PlaudImportProgressResponse(BaseModel):
    """POST /api/plaud/import 在途时的下载进度（同步 handler 里实时更新）。"""

    file_id: str
    # resolving=在取直链，downloading=正在下字节，finalizing=下完在排队，
    # done=导入已返回 201，failed=导入抛错。
    phase: Literal["resolving", "downloading", "finalizing", "done", "failed"]
    bytes_done: int
    # Content-Length；上游没给就是 None。
    bytes_total: int | None = None
    meeting_id: str | None = None
    error: str | None = None


class PlaudRecordingListResponse(BaseModel):
    items: list[PlaudRecordingResponse]
    page: int
    page_size: int
    has_more: bool
    # 是否带了搜索/日期过滤（带过滤时上游忽略分页）。
    filtered: bool
