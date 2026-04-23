from pydantic import BaseModel, Field


class VideoUrlInfo(BaseModel):
    video_id: str = Field(title="video id (photo id)")
    url_type: str = Field(default="normal", title="url type: normal")


class CreatorUrlInfo(BaseModel):
    user_id: str = Field(title="user id (creator id)")
